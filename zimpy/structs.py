# This file is part of pyzim-tools.
#
# pyzim-tools is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License.
#
# pyzim-tools is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pyzim-tools.  If not, see <https://www.gnu.org/licenses/>.

import functools
import lzma
import struct
import threading
import zstandard

CTYPES = {
    _name: struct.Struct("<" + _format)
    for _name, _format in (
        ("c_uint8", "B"),
        ("c_char", "c"),
        ("c_uint16", "H"),
        ("c_uint32", "I"),
        ("c_uint64", "Q"),
    )
}


def read_cstring(buf, offset):
    end_off = buf.find(bytes([0]), offset)
    return buf[offset:end_off].decode(), end_off + 1


class AttributeDescriptor:
    def __init__(self, offset, ctype):
        self.offset = offset
        try:
            self.ctype = CTYPES[ctype]
        except KeyError:
            self.ctype = struct.Struct("<" + ctype)

    def __get__(self, obj, objtype):
        return self.ctype.unpack_from(obj.buf, obj.offset + self.offset)[0]


class MetaBaseStruct(type):
    def __new__(cls, name, bases, attrs):
        fields = attrs.get("_fields_", [])
        offset = 0
        for field in fields:
            if len(field) == 3:
                name_, ctype, size = field
            else:
                name_, ctype = field
                size = None
            attrs[name_] = AttributeDescriptor(offset, ctype)
            if size is None:
                size = attrs[name_].ctype.size
            offset += size
        attrs["csize"] = offset

        return super().__new__(cls, name, bases, attrs)


class MimetypeList(list):
    def __init__(self, buf, offset):
        super().__init__()
        while True:
            mimetype, offset = read_cstring(buf, offset)
            if not mimetype:
                break
            self.append(mimetype)


class BaseStruct(metaclass=MetaBaseStruct):
    def __init__(self, buf, offset):
        self.buf = buf
        self.offset = offset


class BaseList:
    def __init__(self, buf, offset, ctype=CTYPES["c_uint64"]):
        self.buf = buf
        self.offset = offset
        self.ctype = ctype

    def __getitem__(self, index):
        return self.ctype.unpack_from(self.buf, self.offset + index * self.ctype.size)[
            0
        ]


class Header(BaseStruct):
    _fields_ = [
        ("magicNumber", "c_uint32"),
        ("majorVersion", "c_uint16"),
        ("minorVersion", "c_uint16"),
        ("uuid", "16s"),
        ("articleCount", "c_uint32"),
        ("clusterCount", "c_uint32"),
        ("urlPtrPos", "c_uint64"),
        ("titlePtrPos", "c_uint64"),
        ("clusterPtrPos", "c_uint64"),
        ("mimeListPos", "c_uint64"),
        ("mainPage", "c_uint32"),
        ("layoutPage", "c_uint32"),
        ("checksumPos", "c_uint64"),
    ]


class Dirent(BaseStruct):
    def __new__(cls, buf, offset):
        mimetype = CTYPES["c_uint16"].unpack_from(buf[offset : offset + 2])[0]
        if mimetype == 0xFFFF:
            return super(Dirent, cls).__new__(RedirectDirent)
        return super(Dirent, cls).__new__(ArticleDirent)

    @property
    def url(self):
        return read_cstring(self.buf, self.offset + self.csize)[0]

    @property
    def title(self):
        _, off = read_cstring(self.buf, self.offset + self.csize)
        return read_cstring(self.buf, off)[0]


class ArticleDirent(Dirent):
    kind = "article"
    _fields_ = [
        ("mimetype", "c_uint16"),
        ("parameter_len", "c_uint8"),
        ("namespace", "c_char"),
        ("revision", "c_uint32"),
        ("clusterNumber", "c_uint32"),
        ("blobNumber", "c_uint32"),
    ]


class RedirectDirent(Dirent):
    kind = "redirect"
    _fields_ = [
        ("mimetype", "c_uint16"),
        ("parameter_len", "c_uint8"),
        ("namespace", "c_char"),
        ("revision", "c_uint32"),
        ("redirect_index", "c_uint32"),
    ]


@functools.lru_cache
class Cluster(BaseStruct):
    _fields_ = [("info", "c_uint8")]

    def __init__(self, buf, offset):
        super().__init__(buf, offset)
        self._data = None
        self._offsets = None
        self._lock = threading.Lock()

    @property
    def compression(self):
        return self.info & 0b00001111

    @property
    def extended(self):
        return bool(self.info & 0b00010000)

    @property
    def data(self):
        with self._lock:
            if self._data is not None:
                return self._data, 0

            if self.compression == 4:
                decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
                offset = self.offset + 1
                self._data = b""
                while decompressor.needs_input:
                    idata = self.buf[offset : offset + 1024]
                    self._data += decompressor.decompress(idata)
                    offset += 1024
                return self._data, 0
            elif self.compression == 5:
                decompressor = zstandard.ZstdDecompressor().decompressobj()
                offset = self.offset + 1
                self._data = b""
                while True:
                    try:
                        idata = self.buf[offset : offset + 1024]
                        self._data += decompressor.decompress(idata)
                        offset += 1024
                    except zstandard.ZstdError:
                        break
                return self._data, 0
            else:
                return self.buf, self.offset + 1

    @property
    def offsets(self):
        if not self._offsets:
            ctype = CTYPES["c_uint64"] if self.extended else CTYPES["c_uint32"]
            self._offsets = BaseList(*self.data, ctype)
        return self._offsets

    def get_blob_data(self, index):
        data, offset = self.data
        return data[offset + self.offsets[index] : offset + self.offsets[index + 1]]
