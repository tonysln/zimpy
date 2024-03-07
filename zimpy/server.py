import mmap
import re
import sqlite3
import bs4
import flask
import tqdm
from .structs import BaseList, Cluster, Dirent, Header, MimetypeList


class WikiServer:
    def __init__(self, path, port=4321):
        self.app = flask.Flask(__name__)
        with open(path, "rb") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                self.h = Header(mm, 0)
                self.mimes = MimetypeList(self.h.buf, self.h.mimeListPos)
                self.urls = BaseList(self.h.buf, self.h.urlPtrPos)
                self.clusters = BaseList(self.h.buf, self.h.clusterPtrPos)
                self.initialize_db()
                self.register_routes()
                self.app.run(port=port)

    def register_routes(self):
        @self.app.route("/")
        def index():
            return self.render_page(Dirent(self.h.buf, self.urls[self.h.mainPage]))

        @self.app.route("/<path:url>")
        def get_page(url):
            ns, url = ("A", url) if not re.match(r"^[a-zA-Z-]/", url) else url.split("/", 1)
            try:
                idx = self.find_by_url(bytes(ns, "utf-8"), url)
            except IndexError:
                return flask.Response("Not found", status=404)
            d = Dirent(self.h.buf, self.urls[idx])
            while d.kind == "redirect":
                d = Dirent(self.h.buf, self.urls[d.redirect_index])
            return self.render_page(d)

        @self.app.route("/search")
        def search():
            query = flask.request.args.get("q", "")
            with sqlite3.connect("wiki.db") as conn:
                c = conn.cursor()
                c.execute("SELECT title, url FROM articles WHERE title LIKE ? ORDER BY LENGTH(title) LIMIT 100", ("%" + query + "%",))
                results = c.fetchall()

            if len(results) == 1:
                return flask.redirect(flask.url_for("get_page", url=results[0][1]))
            return flask.render_template("search.html", query=query, results=results)

    def render_page(self, dirent):
        c = Cluster(self.h.buf, self.clusters[dirent.clusterNumber])
        if dirent.mimetype == self.mimes.index("text/html"):
            soup = bs4.BeautifulSoup(c.get_blob_data(dirent.blobNumber), "html.parser")
            return flask.render_template("article.html", head=soup.head, body=soup.body)
        return flask.Response(c.get_blob_data(dirent.blobNumber), mimetype=self.mimes[dirent.mimetype])

    def find_by_url(self, ns, url):
        left = 0
        right = self.h.articleCount - 1
        while left <= right:
            mid = (left + right) // 2
            d = Dirent(self.h.buf, self.urls[mid])
            if (d.namespace, d.url) < (ns, url):
                left = mid + 1
            elif (d.namespace, d.url) > (ns, url):
                right = mid - 1
            else:
                return mid
        raise IndexError

    def initialize_db(self):
        with sqlite3.connect("wiki.db") as conn:
            c = conn.cursor()
            c.execute("CREATE TABLE IF NOT EXISTS articles (id INTEGER PRIMARY KEY, title TEXT, url TEXT)")

            c.execute("SELECT COUNT(*) FROM articles")
            if c.fetchone()[0] > 0:
                return

            for i in tqdm.trange(self.h.articleCount):
                d = Dirent(self.h.buf, self.urls[i])
                if (d.kind == "article" and d.namespace == bytes("A", "utf-8") and d.title):
                    c.execute("INSERT INTO articles (title, url) VALUES (?, ?)", (d.title, d.url))

            conn.commit()
