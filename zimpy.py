import sqlite3

from flask import Flask, Response, render_template, request

from structs import *

ARTICLE = "A"
OTHER = "-"


def bisect(compare_function, low, high):
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

    def _compare_url(self, index: int, ns: bytes, url: str):
        d = Dirent(self.header.buf, self.urlPtrList[index])
        if d.namespace == ns and d.url == url:
            return 0
        if d.namespace < ns or (d.namespace == ns and d.url < url):
            return -1
        else:
            return 1

    def _compare_title(self, index: int, ns: bytes, title: str):
        urlIndex = self.titlePtrList[index]
        d = Dirent(self.header.buf, self.urlPtrList[urlIndex])
        title_from_data = d.title or d.url
        if d.namespace == ns and title_from_data == title:
            return 0
        if d.namespace < ns or (d.namespace == ns and title_from_data < title):
            return -1
        else:
            return 1

    def findByUrl(self, ns, url):
        return bisect(lambda index: self._compare_url(index, ns, url), 0, self.header.articleCount)

    def findByTitle(self, ns, title):
        return bisect(lambda index: self._compare_title(index, ns, title), 0, self.header.articleCount)


def create_db():
    with sqlite3.connect("wiki.db") as conn:
        c = conn.cursor()
        c.execute("DROP TABLE IF EXISTS articles")
        c.execute("""CREATE TABLE articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT NOT NULL
        )""")
        conn.commit()


def populate_db(zim: ZIMFile):
    print("Populating database")
    with sqlite3.connect("wiki.db") as conn:
        c = conn.cursor()
        articles = []
        for i in range(zim.header.articleCount):
            dirent = Dirent(zim.header.buf, zim.urlPtrList[i])
            if dirent.namespace == bytes(ARTICLE, "utf-8") and dirent.title and dirent.url:
                articles.append((dirent.title, dirent.url))
        c.executemany("INSERT INTO articles (title, url) VALUES (?, ?)", articles)
        conn.commit()
        print("Added", len(articles), "articles to database")
        # not adding when url or title is missing, also inserting redirects too I guess


def rank_results(query, results):
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
            response = Response(cluster.get_blob_data(dirent.blobNumber))
            response.headers['Content-Type'] = self.zim.mimeList[dirent.mimetype]
            return response

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
                c.execute("SELECT title, url FROM articles WHERE title LIKE ? OR url LIKE ?", ("%" + query + "%", "%" + query + "%"))
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
