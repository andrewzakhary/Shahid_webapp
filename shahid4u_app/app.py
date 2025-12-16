from flask import Flask, render_template, request, redirect, url_for
import requests, re, json, sqlite3
from bs4 import BeautifulSoup
from flask import session


app = Flask(__name__)
app.secret_key = "change-this-to-any-random-string"
DB = "data.db"
HEADERS = {"User-Agent": "Mozilla/5.0"}




# ---------------- DATABASE ----------------
OMDB_API_KEY = "6c38b544"
def fetch_imdb_info(title):
    try:
        r = requests.get(
            "https://www.omdbapi.com/",
            params={
                "apikey": OMDB_API_KEY,
                "t": title,
                "type": "series"
            },
            timeout=10
        ).json()

        if r.get("Response") != "True":
            return fetch_image_from_search(title)  # fallback if OMDb fails

        return {
            "rating": r.get("imdbRating"),
            "year": r.get("Year"),
            "genre": r.get("Genre"),
            "poster": r.get("Poster") if r.get("Poster") != "N/A" else fetch_image_from_search(title)
        }
    except:
        return fetch_image_from_search(title)
def fetch_fallback_poster(title):
    """Try to get first Google Images or Wikipedia image for the series"""
    import urllib.parse
    try:
        # First try Wikipedia
        search_url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
        html = requests.get(search_url, headers=HEADERS, timeout=10).text
        soup = BeautifulSoup(html, "html.parser")
        img = soup.select_one(".infobox img")
        if img:
            poster_url = "https:" + img.get("src")
            return {
                "rating": None,
                "year": None,
                "genre": None,
                "poster": poster_url
            }
    except:
        pass

    try:
        # Fallback: Google Images first result
        query = urllib.parse.quote(title)
        google_url = f"https://www.google.com/search?tbm=isch&q={query}"
        html = requests.get(google_url, headers=HEADERS, timeout=10).text
        soup = BeautifulSoup(html, "html.parser")
        img = soup.select_one("img")
        if img and img.get("src"):
            return {
                "rating": None,
                "year": None,
                "genre": None,
                "poster": img.get("src")
            }
    except:
        pass

    # Final fallback
    return {
        "rating": None,
        "year": None,
        "genre": None,
        "poster": "/static/no-poster.png"
    }
def fetch_image_from_search(title):
    """
    Get first image result from Bing Images search.
    Returns a dict with poster URL and placeholders for rating/year/genre.
    """
    try:
        query = title.replace(" ", "+")
        url = f"https://www.bing.com/images/search?q={query}"
        html = requests.get(url, headers=HEADERS, timeout=10).text
        soup = BeautifulSoup(html, "html.parser")
        
        # Bing image results use 'm' attribute with JSON containing image URL
        img_tag = soup.select_one("a.iusc")
        if img_tag:
            import json
            m = json.loads(img_tag.get("m", "{}"))
            poster_url = m.get("murl")
            if poster_url:
                return {
                    "rating": None,
                    "year": None,
                    "genre": None,
                    "poster": poster_url
                }
    except:
        pass

    # Fallback placeholder
    return {
        "rating": None,
        "year": None,
        "genre": None,
        "poster": "/static/no-poster.png"
    }
def db():
    return sqlite3.connect(DB)
def init_db():
    with db() as con:
        cur = con.cursor()

        # Create base tables
        cur.execute("""
        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_id INTEGER,
            episode_number INTEGER,
            episode_url TEXT
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_id INTEGER,
            server_name TEXT,
            server_url TEXT
        )
        """)

        # ---- SAFE COLUMN MIGRATIONS ----
        def add_column(table, column, col_type):
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            except sqlite3.OperationalError:
                pass  # column already exists
        add_column("collections", "imdb_poster", "TEXT")
        add_column("collections", "imdb_rating", "TEXT")
        add_column("collections", "imdb_year", "TEXT")
        add_column("collections", "imdb_genre", "TEXT")
        add_column("collections", "poster", "TEXT") 
        con.commit()

# ---------------- SCRAPER ----------------

def scrape_season(url):
    html = requests.get(url, headers=HEADERS, timeout=15).text
    soup = BeautifulSoup(html, "html.parser")

    episodes_div = soup.select_one(".d-flex.flex-column.items_container")
    if not episodes_div:
        return []

    episode_links = [a["href"] for a in episodes_div.find_all("a", href=True)]

    data = []

    for idx, ep_url in enumerate(reversed(episode_links)):
        html_ep = requests.get(ep_url, headers=HEADERS, timeout=15).text
        match = re.search(r"JSON\.parse\('(.+?)'\);", html_ep, re.DOTALL)
        if not match:
            continue

        servers_json = match.group(1).encode().decode("unicode_escape")
        servers = json.loads(servers_json)

        data.append({
            "episode": idx+1,
            "url": ep_url,
            "servers": [(s["name"], s["url"]) for s in servers]
        })

    return data

# ---------------- ROUTES ----------------
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        preview = scrape_season(request.form["url"])
        session["preview"] = preview
        return redirect(url_for("index"))  # PRG

    preview = session.get("preview")
    return render_template("index.html", preview=preview)
@app.route("/save", methods=["POST"])
def save():
    name = request.form["name"]
    preview = session.get("preview")

    if not preview:
        return redirect(url_for("index"))

    with db() as con:
        cur = con.cursor()
        cur.execute("INSERT INTO collections (name) VALUES (?)", (name,))
        
        cid = cur.lastrowid
        imdb = fetch_imdb_info(name)

        if imdb:
            cur.execute("""
                UPDATE collections
                SET imdb_rating=?, imdb_year=?, imdb_genre=?, imdb_poster=?
                WHERE id=?
            """, (
                imdb["rating"],
                imdb["year"],
                imdb["genre"],
                imdb["poster"],
                cid
            ))


        for ep in preview:
            cur.execute(
                "INSERT INTO episodes (collection_id, episode_number, episode_url) VALUES (?,?,?)",
                (cid, ep["episode"], ep["url"])
            )
            eid = cur.lastrowid

            for s_name, s_url in ep["servers"]:
                cur.execute(
                    "INSERT INTO servers (episode_id, server_name, server_url) VALUES (?,?,?)",
                    (eid, s_name, s_url)
                )

        con.commit()

    session.pop("preview", None)  # 🔥 clear preview
    return redirect(url_for("library"))

@app.route("/library")
def library():
    q = request.args.get("q", "")
    with db() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, name, imdb_rating, imdb_year, imdb_genre, imdb_poster
            FROM collections
            WHERE name LIKE ?
        """, (f"%{q}%",))

        collections = cur.fetchall()
    return render_template("library.html", collections=collections)


@app.route("/collection/<int:cid>")
def collection(cid):
    with db() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT name, imdb_rating, imdb_year, imdb_genre
            FROM collections WHERE id=?
            """, (cid,))
        name, rating, year, genre = cur.fetchone()


        cur.execute("SELECT id, episode_number FROM episodes WHERE collection_id=?", (cid,))
        episodes = cur.fetchall()

        result = {}
        for eid, ep_no in episodes:
            cur.execute("SELECT server_name, server_url FROM servers WHERE episode_id=?", (eid,))
            result[f"Episode {ep_no}"] = cur.fetchall()

    return render_template("collection.html", result=result, name=name)

@app.route("/delete/<int:cid>", methods=["POST"])
def delete_collection(cid):
    with db() as con:
        cur = con.cursor()
        cur.execute("DELETE FROM servers WHERE episode_id IN (SELECT id FROM episodes WHERE collection_id=?)", (cid,))
        cur.execute("DELETE FROM episodes WHERE collection_id=?", (cid,))
        cur.execute("DELETE FROM collections WHERE id=?", (cid,))
        con.commit()
    return redirect(url_for("library"))
@app.route("/rename/<int:cid>", methods=["POST"])
def rename(cid):
    new_name = request.form["name"]

    with db() as con:
        cur = con.cursor()
        # Update collection name
        cur.execute("UPDATE collections SET name=? WHERE id=?", (new_name, cid))

        # Re-fetch IMDb info and poster based on the new name
        imdb = fetch_imdb_info(new_name)
        if not imdb:
            imdb = fetch_image_from_search(new_name)  # fallback if IMDb fails

        cur.execute("""
            UPDATE collections
            SET imdb_rating=?, imdb_year=?, imdb_genre=?, poster=?
            WHERE id=?
        """, (imdb["rating"], imdb["year"], imdb["genre"], imdb["poster"], cid))

        con.commit()

    return redirect(url_for("library"))


# ----------------

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
