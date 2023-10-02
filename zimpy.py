from flask import Flask, Response

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


class ZIMServer:
    def __init__(self, file_path: str):
        self.zim = ZIMFile(file_path)
        self.app = Flask(__name__)

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
            response = Response(content)
            response.headers['Content-Type'] = self.zim.mimeList[dirent.mimetype]
            return response


if __name__ == '__main__':
    server = ZIMServer("wiki.zim")
    server.app.run()
