"""Utilidades para forzar que los adjuntos subidos desde el portal sean PDF.

La validación se hace en servidor, comprobando tanto la extensión ``.pdf`` como la
cabecera mágica ``%PDF`` del contenido, sin consumir el stream del fichero (se
restaura la posición tras leer los primeros bytes) para no romper la lectura
posterior en los controllers.
"""

from odoo import _
from odoo.exceptions import UserError

_PDF_MAGIC = b"%PDF"
_XLSX_MAGIC = b"PK\x03\x04"
_XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_EXCEL_EXTENSIONS = (".xls", ".xlsx")


def _has_file(file_storage):
    return bool(file_storage) and bool(getattr(file_storage, "filename", ""))


def is_pdf(file_storage):
    """Devuelve True si el fichero es un PDF válido por extensión y cabecera."""
    if not _has_file(file_storage):
        return False
    if not file_storage.filename.lower().endswith(".pdf"):
        return False
    stream = file_storage.stream
    position = stream.tell()
    header = stream.read(len(_PDF_MAGIC))
    stream.seek(position)
    return header == _PDF_MAGIC


def ensure_pdf(*file_storages):
    """Valida que todos los ficheros aportados sean PDF.

    Los campos de fichero vacíos se ignoran (permite adjuntos opcionales). Si algún
    fichero no es PDF se lanza ``UserError`` con un mensaje claro para el usuario.
    """
    for file_storage in file_storages:
        if not _has_file(file_storage):
            continue
        if not is_pdf(file_storage):
            raise UserError(
                _(
                    "Solo se permiten archivos en formato PDF. "
                    "El archivo «%s» no es un PDF válido."
                )
                % file_storage.filename
            )


def is_excel(file_storage):
    """Devuelve True si el fichero es un Excel (.xls o .xlsx) válido por extensión y cabecera."""
    if not _has_file(file_storage):
        return False
    if not file_storage.filename.lower().endswith(_EXCEL_EXTENSIONS):
        return False
    stream = file_storage.stream
    position = stream.tell()
    header = stream.read(len(_XLS_MAGIC))
    stream.seek(position)
    return header.startswith(_XLSX_MAGIC) or header == _XLS_MAGIC


def ensure_excel(*file_storages):
    """Valida que todos los ficheros aportados sean Excel (.xls o .xlsx).

    Los campos de fichero vacíos se ignoran (permite adjuntos opcionales). Si algún
    fichero no es un Excel válido se lanza ``UserError`` con un mensaje claro para el
    usuario.
    """
    for file_storage in file_storages:
        if not _has_file(file_storage):
            continue
        if not is_excel(file_storage):
            raise UserError(
                _(
                    "Solo se permiten archivos en formato Excel (.xls o .xlsx). "
                    "El archivo «%s» no es un Excel válido."
                )
                % file_storage.filename
            )
