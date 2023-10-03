import sqlite3
import mmap
from typing import List, Tuple

from flask import Flask, Response, render_template, request
from structs import *

ARTICLE = "A"
OTHER = "-"


def bisect(compare_function, low, high):
    """Bisect the given range using the given compare function"""
    while low < high:
        middle = (low + high) // 2
        comp = compare_function(middle)
        if comp == 0:
            return middle
        if comp < 0:
            low = middle
        else:
            high = middle

    raise IndexError


class ZIMFile:
    def __init__(self, file_path: str):
        with open(file_path, "rb") as f:
            self.mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            self.header = Header(self.mm, 0)
            self.mimeList = MimeTypeList(self.mm, self.header.mimeListPos)
            self.urlPtrList = UrlPtrList(self.mm, self.header.urlPtrPos)
            self.titlePtrList = TitlePtrList(self.mm, self.header.titlePtrPos)
            self.clusterPtrList = ClusterPtrList(self.mm, self.header.clusterPtrPos)
            print(self.header)

    def _compare_url(self, index: int, ns: bytes, url: str) -> int:
        """Compare the url of the dirent at the given index with the given url in the given namespace"""
        d = Dirent(self.header.buf, self.urlPtrList[index])
        if d.namespace == ns and d.url == url:
            return 0
        if d.namespace < ns or (d.namespace == ns and d.url < url):
            return -1
        else:
            return 1

    def _compare_title(self, index: int, ns: bytes, title: str) -> int:
        """Compare the title of the dirent at the given index with the given title in the given namespace"""
        urlIndex = self.titlePtrList[index]
        d = Dirent(self.header.buf, self.urlPtrList[urlIndex])
        title_from_data = d.title or d.url
        if d.namespace == ns and title_from_data == title:
            return 0
        if d.namespace < ns or (d.namespace == ns and title_from_data < title):
            return -1
        else:
            return 1

    def findByUrl(self, ns, url) -> int:
        """Find the index of the dirent with the given url in the given namespace"""
        return bisect(lambda index: self._compare_url(index, ns, url), 0, self.header.entryCount)

    def findByTitle(self, ns, title) -> int:
        """Find the index of the dirent with the given title in the given namespace"""
        return bisect(lambda index: self._compare_title(index, ns, title), 0, self.header.entryCount)


def create_and_populate_db(zim: ZIMFile, batch_size: int = 1000) -> None:
    """Create and populate the database with the entries from the zim file"""
    with sqlite3.connect("wiki.db") as conn:
        c = conn.cursor()

        c.execute("""CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY,
            title TEXT,
            url TEXT,
            namespace TEXT
            )""")
        conn.commit()

        c.execute("SELECT COUNT(*) FROM entries")
        if c.fetchone()[0] > 0:
            print("Database is already populated. Skipping...")
            return

        print("Populating database...")
        batch: List[Tuple[str, str, str]] = []
        for i in range(zim.header.entryCount):
            if i % (zim.header.entryCount // 10) == 0:
                print(f"{i / zim.header.entryCount * 100:.2f}%")
            dirent = Dirent(zim.header.buf, zim.urlPtrList[i])
            if dirent.namespace.decode("utf-8") == ARTICLE:
                title = dirent.title or dirent.url
                batch.append((title, dirent.url, dirent.namespace.decode("utf-8")))

                if len(batch) == batch_size:
                    c.executemany("INSERT INTO entries (title, url, namespace) VALUES (?, ?, ?)", batch)
                    batch.clear()

        if batch:
            c.executemany("INSERT INTO entries (title, url, namespace) VALUES (?, ?, ?)", batch)
        c.execute("CREATE INDEX IF NOT EXISTS title_index ON entries (title)")
        conn.commit()
        print("Done")


def rank_results(query: str, results: list) -> list:
    """Rank the results by the length of the match divided by the length of the title"""
    def ranker(item):
        title, url = item
        match_length = len(query)
        title_length = len(title)
        score = match_length / title_length
        return -score

    return sorted(results, key=ranker)


class ZIMServer:
    def __init__(self, file_path: str):
        self.zim = ZIMFile(file_path)
        self.app = Flask(__name__)

        create_and_populate_db(self.zim)

        @self.app.route("/")
        def index():
            dirent = Dirent(self.zim.header.buf, self.zim.urlPtrList[self.zim.header.mainPage])
            cluster = Cluster(self.zim.header.buf, self.zim.clusterPtrList[dirent.clusterNumber])
            return cluster.get_blob_data(dirent.blobNumber)

        @self.app.route("/favicon.ico")
        def favicon():
            return "No content", 204

        @self.app.route("/w/<path:url>")
        def w(url):
            return "Not found", 404

        @self.app.route("/search")
        def search():
            query = request.args.get("q")
            if not query:
                return "No query", 400

            with sqlite3.connect("wiki.db") as conn:
                c = conn.cursor()
                db_query = "%" + "%".join(query.split()) + "%"
                c.execute("SELECT title, url FROM entries WHERE title LIKE ? LIMIT 1000", (db_query,))
                results = c.fetchall()

            results = rank_results(query, results)
            return render_template("search.html", query=query, results=results)

        @self.app.route("/<path:url>")
        def url(url):
            if "/" not in url:
                url = str(ARTICLE) + "/" + url
            _ns, _url = url.split("/", 1)
            dirent = Dirent(self.zim.header.buf, self.zim.urlPtrList[self.zim.findByUrl(bytes(_ns, "utf-8"), _url)])
            while dirent.kind == "redirect":
                index = dirent.redirect_index
                dirent = Dirent(self.zim.header.buf, self.zim.urlPtrList[index])
            cluster = Cluster(self.zim.header.buf, self.zim.clusterPtrList[dirent.clusterNumber])
            content = cluster.get_blob_data(dirent.blobNumber)
            if self.zim.mimeList[dirent.mimetype] == "text/html":
                head = content.split(b"<head>", 1)[1].split(b"</head>", 1)[0]
                body = content.split(b"<body", 1)[1].split(b">", 1)[1].rsplit(b"</body>", 1)[0]
                return render_template("base.html", head=head.decode("utf-8"), body=body.decode("utf-8"))
            response = Response(content)
            response.headers['Content-Type'] = self.zim.mimeList[dirent.mimetype]
            return response


if __name__ == '__main__':
    server = ZIMServer("wiki.zim")
    server.app.run()
