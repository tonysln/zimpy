import sqlite3
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
        self.file = open(file_path, "rb")
        self.header = Header(self.file.read(), 0)
        self.mimeList = MimeTypeList(self.header.buf, self.header.mimeListPos)
        self.urlPtrList = UrlPtrList(self.header.buf, self.header.urlPtrPos)
        self.titlePtrList = TitlePtrList(self.header.buf, self.header.titlePtrPos)
        self.clusterPtrList = ClusterPtrList(self.header.buf, self.header.clusterPtrPos)

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
        return bisect(lambda index: self._compare_url(index, ns, url), 0, self.header.articleCount)

    def findByTitle(self, ns, title) -> int:
        """Find the index of the dirent with the given title in the given namespace"""
        return bisect(lambda index: self._compare_title(index, ns, title), 0, self.header.articleCount)


def create_db() -> None:
    """Create the database"""
    with sqlite3.connect("wiki.db") as conn:
        c = conn.cursor()
        c.execute("DROP TABLE IF EXISTS entries")
        c.execute("""CREATE TABLE entries (
            id INTEGER PRIMARY KEY,
            title TEXT,
            url TEXT UNIQUE,
            namespace TEXT
            )""")
        conn.commit()


def populate_db(zim: ZIMFile) -> None:
    """Populate the database with the entries from the zim file"""
    print("Populating database...")
    with sqlite3.connect("wiki.db") as conn:
        c = conn.cursor()
        entries = []
        for i in range(zim.header.articleCount):
            dirent = Dirent(zim.header.buf, zim.urlPtrList[i])
            entries.append((dirent.title, dirent.url, dirent.namespace.decode("utf-8")))
        c.executemany("INSERT INTO entries (title, url, namespace) VALUES (?, ?, ?)", entries)
        c.execute("CREATE INDEX title_index ON entries (title)")
        conn.commit()
        print("Added", len(entries), "entries")


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

        create_db()
        populate_db(self.zim)

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
                c.execute("SELECT title, url FROM entries WHERE title LIKE ? AND namespace = ?",
                          (f"%{query}%", ARTICLE))
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
