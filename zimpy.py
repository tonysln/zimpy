import mmap
import sqlite3

from flask import Flask, Response, render_template, request
from tqdm import trange

from structs import *


def bisect(compare_function, low: int, high: int):
    """Bisect a sorted list and return the index of the element that matches the compare function"""
    while low < high:
        middle = (low + high) // 2
        comp = compare_function(middle)
        if comp == 0:
            return middle
        if comp < 0:
            low = middle + 1
        else:
            high = middle

    raise IndexError


class ZIMFile:
    def __init__(self, file_path: str) -> None:
        """Open the ZIM file and read the header"""
        with open(file_path, "rb") as f:
            self._mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            self.header = Header(self._mm, 0)
            self.mimeList = MimeTypeList(self._mm, self.header.mimeListPos)
            self.urlPtrList = UrlPtrList(self._mm, self.header.urlPtrPos)
            self.titlePtrList = TitlePtrList(self._mm, self.header.titlePtrPos)
            self.clusterPtrList = ClusterPtrList(self._mm, self.header.clusterPtrPos)
            print(self.header)

    def _compare_url(self, index: int, ns: bytes, url: str) -> int:
        """Compare the url at the given index with the given url"""
        d = Dirent(self.header.buf, self.urlPtrList[index])
        if d.namespace == ns and d.url == url:
            return 0
        if d.namespace < ns or (d.namespace == ns and d.url < url):
            return -1
        else:
            return 1

    def findByUrl(self, ns: bytes, url: str) -> int:
        """Find the index of the url in the urlPtrList"""
        try:
            return bisect(lambda index: self._compare_url(index, ns, url), 0, self.header.entryCount)
        except IndexError:
            return -1


def _initialize_db(zim: ZIMFile) -> None:
    """Initialize the database and populate it with the articles"""
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
        for i in trange(zim.header.entryCount):
            _dirent = Dirent(zim.header.buf, zim.urlPtrList[i])
            if _dirent.namespace == b"A":
                _title = _dirent.title or _dirent.url
                _entry = (_title, _dirent.url, _dirent.namespace.decode("utf-8"))
                c.executemany("INSERT INTO entries (title, url, namespace) VALUES (?, ?, ?)", (_entry,))

        _article_count = c.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        print(f"Found {_article_count} articles, creating indexes...")
        c.execute("CREATE INDEX IF NOT EXISTS title_index ON entries (title)")
        conn.commit()


class ZIMServer:
    def __init__(self, file_path: str, template: str = "base.html") -> None:
        """Initialize the ZIM server"""
        self._zim = ZIMFile(file_path)
        self._template = template
        self.app = Flask(__name__)

        _initialize_db(self._zim)

        @self.app.route("/")
        def index():
            """Render the main page"""
            _dirent = Dirent(self._zim.header.buf, self._zim.urlPtrList[self._zim.header.mainPage])
            _cluster = Cluster(self._zim.header.buf, self._zim.clusterPtrList[_dirent.clusterNumber])
            _content = _cluster.get_blob_data(_dirent.blobNumber).decode("utf-8")
            return self._render_template(_content)

        @self.app.route("/favicon.ico")
        def favicon():
            """Return a 204 No Content response for the favicon"""
            return "No content", 204

        @self.app.route("/w/<path:url>")
        def w(url):
            """A /w/load.php... is requested, return a 204 No Content response"""
            return f"No content for {url[:5]}", 204

        @self.app.route("/search")
        def search():
            """Search for a query in the database"""
            _query = request.args.get("q")
            if not _query:
                return "No query", 400

            with sqlite3.connect("wiki.db") as conn:
                c = conn.cursor()
                db_query = "%" + "%".join(_query.split()) + "%"
                c.execute("SELECT title, url FROM entries WHERE title LIKE ? ORDER BY LENGTH(title) LIMIT 100",
                          (db_query,))
                _results = c.fetchall()

            if not _results:
                return render_template("base.html", head="", body=f"No results for {_query}")

            if len(_results) == 1:
                return url(_results[0][1])

            return render_template("search.html", query=_query, results=_results)

        @self.app.route("/<path:url>")
        def url(url):
            """Return the requested url"""
            if "/" not in url:
                url = "A/" + url
            _ns, _url = url.split("/", 1)
            _idx = self._zim.findByUrl(bytes(_ns, "utf-8"), _url)
            if _idx == -1:
                return render_template("base.html", head="", body=f"Page {url} not found")
            _dirent = Dirent(self._zim.header.buf, self._zim.urlPtrList[_idx])
            while _dirent.kind == "redirect":
                _index = _dirent.redirect_index
                _dirent = Dirent(self._zim.header.buf, self._zim.urlPtrList[_index])
            _cluster = Cluster(self._zim.header.buf, self._zim.clusterPtrList[_dirent.clusterNumber])
            _content = _cluster.get_blob_data(_dirent.blobNumber)
            if self._zim.mimeList[_dirent.mimetype] == "text/html":
                return self._render_template(_content.decode("utf-8"))
            _response = Response(_content)
            _response.headers['Content-Type'] = self._zim.mimeList[_dirent.mimetype]
            return _response

    def _render_template(self, content: str) -> str:
        """Render the template with the given content"""
        _head = content.split("<head>", 1)[1].split("</head>", 1)[0]
        _body = content.split("<body", 1)[1].split(">", 1)[1].rsplit("</body>", 1)[0]
        return render_template(self._template, head=_head, body=_body)
