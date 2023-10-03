import mmap
import struct
from lzma import LZMADecompressor, FORMAT_XZ
from typing import Tuple

from zstandard import ZstdDecompressor, ZstdError

ZERO = bytes([0])
ENCODING = "utf-8"
LZMA2 = 4
ZSTD = 5

CTYPES = {}
for t in (("c_uint8", "B"), ("c_char", "c"), ("c_uint16", "H"), ("c_uint32", "I"), ("c_uint64", "Q"),):
    _name, _format = t
    CTYPES[_name] = struct.Struct("<" + _format)

__all__ = ["MimeTypeList", "UrlPtrList", "TitlePtrList", "ClusterPtrList", "Header", "Dirent", "Cluster", ]


class AttributeDescriptor:
    def __init__(self, offset: int, ctype: str):
        self.offset = offset
        try:
            self.ctype = CTYPES[ctype]
        except KeyError:
            self.ctype = struct.Struct("<" + ctype)

    def __get__(self, obj, objtype):
        return self.ctype.unpack_from(obj.buf, obj.offset + self.offset)[0]


class MetaBaseStruct(type):
    def __new__(cls, name: str, bases: Tuple[type], attrs: dict) -> type:
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


class MimeTypeList:
    def __init__(self, buf, offset: int):
        self.buf = buf
        self.offset = offset

    def __getitem__(self, index: int):
        off = self.offset
        for i in range(index):
            end_off = self.buf.find(ZERO, off)
            if end_off == off:
                # empty string, end of the mimelist.
                raise IndexError
            off = end_off + 1
        end_off = self.buf.find(ZERO, off)
        if end_off == off:
            raise IndexError
        return self.buf[off:end_off].decode(ENCODING)

    def __len__(self):
        end_buf = self.buf.find(bytes([0, 0]), self.offset)
        return self.buf.count(ZERO, self.offset, end_buf + 1)

    def __str__(self):
        return ", ".join(self[i] for i in range(len(self)))


class BaseArray:
    __slots__ = ("buf", "offset", "ctype")

    def __init__(self, buf: mmap, offset: int):
        self.buf = buf
        self.offset = offset

    def __getitem__(self, index: int):
        offset = self.offset + index * self.ctype.size
        try:
            return self.ctype.unpack_from(self.buf, offset)[0]
        except struct.error:
            raise IndexError

    def __len__(self):
        return (len(self.buf) - self.offset) // self.ctype.size


class UrlPtrList(BaseArray):
    ctype = CTYPES["c_uint64"]


class TitlePtrList(BaseArray):
    ctype = CTYPES["c_uint32"]


class ClusterPtrList(BaseArray):
    ctype = CTYPES["c_uint64"]


class BaseStruct(metaclass=MetaBaseStruct):
    __slots__ = ("buf", "offset")

    def __init__(self, buf: mmap, offset: int):
        self.buf = buf
        self.offset = offset


class Header(BaseStruct):
    _fields_ = [("magicNumber", "c_uint32"), ("majorVersion", "c_uint16"), ("minorVersion", "c_uint16"),
                ("uuid", "16s"), ("entryCount", "c_uint32"), ("clusterCount", "c_uint32"), ("urlPtrPos", "c_uint64"),
                ("titlePtrPos", "c_uint64"), ("clusterPtrPos", "c_uint64"), ("mimeListPos", "c_uint64"),
                ("mainPage", "c_uint32"), ("layoutPage", "c_uint32"), ("_checksumPos", "c_uint64"), ]

    @property
    def size(self):
        return self.mimeListPos

    @property
    def checksumPos(self):
        if self.mimeListPos < 80:
            raise ValueError("Header has no checksumPos")
        return self._checksumPos

    def __str__(self):
        return f"ZIM Header: version {self.majorVersion}.{self.minorVersion}, {self.entryCount} entries, " \
                  f"{self.clusterCount} clusters"


class Dirent(BaseStruct):
    def __new__(cls, buf: bytes, offset: int):
        mimetype = CTYPES["c_uint16"].unpack_from(buf[offset:offset + 2])[0]
        if mimetype == 0xFFFF:
            return super(Dirent, cls).__new__(RedirectDirent)
        return super(Dirent, cls).__new__(ContentDirent)

    @property
    def url(self):
        off = self.offset + self.csize
        end_off = self.buf.find(ZERO, off)
        return self.buf[off:end_off].decode()

    @property
    def title(self):
        off = self.offset + self.csize
        off = self.buf.find(ZERO, off) + 1
        end_off = self.buf.find(ZERO, off)
        return self.buf[off:end_off].decode()

    @property
    def extra_data(self):
        off = self.offset + self.csize
        off = self.buf.find(ZERO, off) + 1
        off = self.buf.find(ZERO, off) + 1
        return self.buf[off:off + self.parameter_len]

    def __str__(self):
        return f"{self.kind} url: {self.url}, title: {self.title}"


class ContentDirent(Dirent):
    kind = "content"
    _fields_ = [("mimetype", "c_uint16"), ("parameter_len", "c_uint8"), ("namespace", "c_char"),
                ("revision", "c_uint32"), ("clusterNumber", "c_uint32"), ("blobNumber", "c_uint32"), ]


class RedirectDirent(Dirent):
    kind = "redirect"
    _fields_ = [("mimetype", "c_uint16"), ("parameter_len", "c_uint8"), ("namespace", "c_char"),
                ("revision", "c_uint32"), ("redirect_index", "c_uint32"), ]


class NormalBlobOffsetArray(BaseArray):
    ctype = CTYPES["c_uint32"]


class ExtendedBlobOffsetArray(BaseArray):
    ctype = CTYPES["c_uint64"]


class Cluster(BaseStruct):
    _fields_ = [("info", "c_uint8")]

    def __init__(self, buf: bytes, offset: int):
        super().__init__(buf, offset)
        self._data = None
        self._offsetArray = None

    @property
    def compression(self):
        return self.info & 0b00001111

    @property
    def extended(self):
        return bool(self.info & 0b00010000)

    @property
    def data(self):
        if self.compression == LZMA2:
            if self._data is None:
                decompressor = LZMADecompressor(format=FORMAT_XZ)
                offset = self.offset + 1
                self._data = b""
                while decompressor.needs_input:
                    idata = self.buf[offset:offset + 1024]
                    self._data += decompressor.decompress(idata)
                    offset += 1024
            return self._data, 0
        elif self.compression == ZSTD:
            if self._data is None:
                decompressor = ZstdDecompressor().decompressobj()
                offset = self.offset + 1
                self._data = b""
                while True:
                    try:
                        idata = self.buf[offset:offset + 1024]
                        self._data += decompressor.decompress(idata)
                        offset += 1024
                    except ZstdError:
                        break
            return self._data, 0
        else:
            return self.buf, self.offset + 1

    @property
    def offsetArray(self):
        if self._offsetArray is None:
            OffsetArrayType = (ExtendedBlobOffsetArray if self.extended else NormalBlobOffsetArray)
            self._offsetArray = OffsetArrayType(*self.data)
        return self._offsetArray

    @property
    def nb_blobs(self):
        return self.nb_offsets - 1

    @property
    def nb_offsets(self):
        first_offset = self.offsetArray[0]
        ctype = CTYPES["c_uint64"] if self.extended else CTYPES["c_uint32"]
        return first_offset // ctype.size

    def get_blob_offset(self, index):
        if index >= self.nb_offsets:
            raise IndexError
        return self.offsetArray[index]

    def get_blob_data(self, index):
        blob_offset = self.get_blob_offset(index)
        end_offset = self.get_blob_offset(index + 1)
        data, offset = self.data
        return data[offset + blob_offset:offset + end_offset]
