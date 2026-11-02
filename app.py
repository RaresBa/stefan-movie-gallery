import os
from urllib.parse import urlsplit

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFError, CSRFProtect


app = Flask(__name__)

# Deployment and database configuration.
on_vercel = os.environ.get("VERCEL") == "1"
database_url = os.environ.get("DATABASE_URL", "").strip()
secret_key = os.environ.get("SECRET_KEY", "").strip()

if on_vercel and (not database_url or not secret_key):
    raise RuntimeError(
        "Set DATABASE_URL and SECRET_KEY in Vercel before deploying."
    )

# Use Psycopg 3 for PostgreSQL connections.
# The hostname, password, database name, and SSL parameters are preserved.
if database_url.startswith("postgres://"):
    database_url = database_url.replace(
        "postgres://",
        "postgresql+psycopg://",
        1,
    )
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1,
    )

# Local development uses SQLite when DATABASE_URL is not set.
database_url = database_url or "sqlite:///movies.db"
uses_postgres = database_url.startswith("postgresql+psycopg://")

if on_vercel and not uses_postgres:
    raise RuntimeError(
        "Use a PostgreSQL DATABASE_URL for this Vercel deployment."
    )

app.config.update(
    SECRET_KEY=secret_key or "dev-only-change-before-deploying",
    SQLALCHEMY_DATABASE_URI=database_url,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=on_vercel,
    MAX_CONTENT_LENGTH=64 * 1024,
)

if uses_postgres:
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
    }

db = SQLAlchemy(app)
csrf = CSRFProtect(app)


GENRES = [
    "Action",
    "Adventure",
    "Animation",
    "Comedy",
    "Crime",
    "Documentary",
    "Drama",
    "Fantasy",
    "Horror",
    "Mystery",
    "Romance",
    "Science fiction",
    "Thriller",
    "Other",
]


class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    genre = db.Column(db.String(50), nullable=False)
    duration = db.Column(db.Integer, nullable=False)
    where_to_watch = db.Column(db.String(200), nullable=False)
    poster_url = db.Column(db.String(2048), nullable=False, default="")
    watched = db.Column(db.Boolean, nullable=False, default=False)

    @property
    def poster_style(self):
        return ("orbit", "sunrise", "city")[(self.id - 1) % 3]


@app.cli.command("init-db")
def init_db():
    """Create missing database tables without deleting existing movies."""
    db.create_all()
    print(f"Database ready ({db.engine.dialect.name}).")


def render_watchlist(form_data=None, errors=None):
    movies = db.session.scalars(
        db.select(Movie).order_by(
            Movie.watched.asc(),
            Movie.id.desc(),
        )
    ).all()

    watched_count = sum(movie.watched for movie in movies)

    return render_template(
        "index.html",
        movies=movies,
        genres=GENRES,
        watched_count=watched_count,
        unwatched_count=len(movies) - watched_count,
        form_data=form_data or {},
        errors=errors or [],
    )


def valid_poster_url(value):
    if not value:
        return True

    if len(value) > 2048:
        return False

    if any(
        char.isspace() or ord(char) < 32 or ord(char) == 127
        for char in value
    ):
        return False

    try:
        parts = urlsplit(value)
        port = parts.port

        return (
            parts.scheme in ("http", "https")
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
            and (port is None or port > 0)
        )
    except ValueError:
        return False


@app.get("/")
def index():
    return render_watchlist()


@app.post("/add")
def add_movie():
    fields = (
        "title",
        "genre",
        "duration",
        "where_to_watch",
        "poster_url",
    )

    form_data = {
        field: request.form.get(field, "").strip()
        for field in fields
    }

    errors = []

    if not 1 <= len(form_data["title"]) <= 200:
        errors.append(
            "Enter a movie title between 1 and 200 characters."
        )

    if form_data["genre"] not in GENRES:
        errors.append("Choose a genre from the list.")

    duration = None

    try:
        duration = int(form_data["duration"])

        if not 1 <= duration <= 2_147_483_647:
            raise ValueError
    except ValueError:
        errors.append(
            "Enter a valid positive whole number for the length in minutes."
        )

    if not 1 <= len(form_data["where_to_watch"]) <= 200:
        errors.append(
            "Enter where to watch the movie, using 1 to 200 characters."
        )

    if not valid_poster_url(form_data["poster_url"]):
        errors.append(
            "Use a valid http:// or https:// poster URL, or leave it blank."
        )

    if errors:
        return render_watchlist(
            form_data=form_data,
            errors=errors,
        ), 400

    movie = Movie(
        title=form_data["title"],
        genre=form_data["genre"],
        duration=duration,
        where_to_watch=form_data["where_to_watch"],
        poster_url=form_data["poster_url"],
    )

    db.session.add(movie)
    db.session.commit()

    flash(
        f'Added "{movie.title}" to your watchlist.',
        "success",
    )

    return redirect(url_for("index"), code=303)


@app.post("/toggle/<int:movie_id>")
def toggle_movie(movie_id):
    movie = db.get_or_404(Movie, movie_id)

    movie.watched = not movie.watched
    db.session.commit()

    status = "watched" if movie.watched else "unwatched"

    flash(
        f'Marked "{movie.title}" as {status}.',
        "success",
    )

    return redirect(url_for("index"), code=303)


@app.post("/delete/<int:movie_id>")
def delete_movie(movie_id):
    movie = db.get_or_404(Movie, movie_id)
    title = movie.title

    db.session.delete(movie)
    db.session.commit()

    flash(
        f'Deleted "{title}" from your watchlist.',
        "success",
    )

    return redirect(url_for("index"), code=303)


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    return render_watchlist(
        form_data=request.form.to_dict(),
        errors=[
            "The form expired or could not be verified. "
            "Please try the action again."
        ],
    ), 400


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5001,
    )