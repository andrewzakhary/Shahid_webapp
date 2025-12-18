from flask import Flask, render_template, request, redirect, url_for
import requests, re, json, sqlite3
from bs4 import BeautifulSoup
from flask import session


app = Flask(__name__)
app.secret_key = "change-this-to-any-random-string"
DB = "data.db"
HEADERS = {"User-Agent": "Mozilla/5.0"}

seasons=['الاول','الثاني','الثالث','الرابع','الخامس','السادس','السابع','الثامن','التاسع','العاشر',
         'الحادي-عشر','الثاني-عشر','الثالث-عشر','الرابع-عشر','الخامس-عشر','السادس-عشر','السابع-عشر','الثامن-عشر','التاسع-عشر','العشرون']

MAX_RETRIES=4
# ---------------- DATABASE ----------------
OMDB_API_KEY = "6c38b544"
API_KEY='3536b9a5811d681b718ece4058a6e85f'

def get_media_poster(api_key, title, media_type="movie", season_number=None):
    base_url = "https://api.themoviedb.org/3"
    img_config_url = "https://image.tmdb.org/t/p/w500" # w500 is a standard width
    
    # 1. Search for the Media ID
    search_url = f"{base_url}/search/{media_type}"
    params = {"api_key": api_key, "query": title}
    
    search_res = requests.get(search_url, params=params).json()
    if not search_res.get('results'):
        return "No results found."
    
    media_id = search_res['results'][0]['id']
    
    # 2. Get the Poster Path
    if media_type == "tv" and season_number is not None:
        # Fetch specific season details
        season_url = f"{base_url}/tv/{media_id}/season/{season_number}"
        res = requests.get(season_url, params={"api_key": api_key}).json()
        poster_path = res.get('poster_path')
        release_date = search_res['results'][0].get('release_date')
    else:
        # Use the main poster path from search results
        poster_path = search_res['results'][0].get('poster_path')
        release_date = search_res['results'][0].get('release_date')[:4]
    
    if poster_path:
        return [img_config_url + poster_path, release_date]
    return "Poster not available."


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
        html_ep = requests.get(url, headers=HEADERS, timeout=15).text
        match = re.search(r"JSON\.parse\('(.+?)'\);", html_ep, re.DOTALL)
        data = []
        servers_json = match.group(1).encode().decode("unicode_escape")
        servers = json.loads(servers_json)

        data=[{
            "episode": 0,
            "url": url,
            "servers": [(s["name"], s["url"]) for s in servers]
        }]
        return data

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
        if request.form["url"].startswith("http"):
            preview = scrape_season(request.form["url"])
        else:
            if request.form["type"]=='movie':
                print(fetch_imdb_info(request.form["url"]))
                _,year=get_media_poster(API_KEY, request.form["url"], media_type="movie")
                print(year)
                url_og='https://shaheid4u.day/watch/%D9%81%D9%8A%D9%84%D9%85-titanic-1997-%D9%85%D8%AA%D8%B1%D8%AC%D9%85'
                url_new=url_og.replace("titanic-1997", f'{request.form["url"].replace(" ","-")}-{year}')
                print(url_new)
                preview = scrape_season(url_new)

            else:
                url_og='https://shaheid4u.day/watch/مسلسل-friends-الموسم-الاول-الحلقة-1-الاولي-مترجمة'
                url_new=url_og.replace("friends", request.form["url"].replace(' ','-'))
                url_new=url_new[:60].replace("الاول", seasons[int(request.form["season"])-1])+url_new[60:]
                print(url_new)
                for attempt in range(MAX_RETRIES):
                    if attempt == 0:
                        try:
                            preview = scrape_season(url_new)
                            break  # success → exit loop
                        except :
                            print(f"Invalid input. Attempts left: {MAX_RETRIES - attempt - 1}")
                    elif attempt==1:
                        try:
                            # url_new=url_new[:60].replace("الاول", seasons[int(request.form["season"])-1])+url_new[60:]
                            url_new=url_new[:60]+url_new[60:].replace('-الاولي','')
                            print(url_new)
                            preview = scrape_season(url_new)
                            break  # success → exit loop
                        except :
                            print(f"Invalid input. Attempts left: {MAX_RETRIES - attempt - 1}")
                    elif attempt==2:
                        try:
                            # url_new=url_new[:60].replace("الاول", seasons[int(request.form["season"])-1])+url_new[60:]
                            url_new=url_new[:60]+url_new[60:].replace('-مترجمة','')
                            print(url_new)
                            preview = scrape_season(url_new)
                            break  # success → exit loop
                        except :
                            print(f"Invalid input. Attempts left: {MAX_RETRIES - attempt - 1}")
                    else:
                        preview = []  # final failure

        session["preview"] = preview 
        return redirect(url_for("index")) # PRG

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
