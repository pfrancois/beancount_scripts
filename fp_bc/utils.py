# -*- coding: utf-8 -*-

import decimal
import re
import typing as t
import csv
import logging
import pprint
import datetime
import time
import math
from uuid import uuid4
from beancount.core import data  # pylint:disable=E0611
from beancount.parser import printer
from io import StringIO

# import sys
from beancount import loader
from collections.abc import Iterable


class ExcelCsv(csv.Dialect):  # pylint: disable=R0903
    """Describe the usual properties of Excel-generated CSV files."""

    delimiter = ";"
    quotechar = '"'
    doublequote = True
    skipinitialspace = False
    lineterminator = "\r\n"
    quoting = csv.QUOTE_MINIMAL


# noinspection PyTypeChecker
csv.register_dialect("excel_csv", ExcelCsv)


class CsvUnicodeReader:  # pylint: disable=E1136
    """
    A CSV reader which will iterate over lines in the CSV file "f",
    which is encoded in the given encoding.
    """

    def __str__(self) -> str:  # pragma: no cover
        return pprint.pformat(self.row)

    def __repr__(self) -> str:
        return pprint.pformat(self.row)

    def __init__(
        self, fich: t.IO, dialect: t.Any = ExcelCsv, champs: t.List[str] = None, champ_detail: str = "detail", ligne_saut: int = 0,
    ) -> None:  # pylint: disable=W0231, E1136
        if champs:
            self.champs = champs
        self.logger = logging.getLogger("CsvUnicodeReader")  # pylint: disable=W0612
        self.reader = csv.DictReader(fich, dialect=dialect, fieldnames=self.champs)
        self.frais = decimal.Decimal(0)
        self.champ_detail = champ_detail
        self.ligne_saut = ligne_saut
        self.line = 0

    def __next__(self) -> "CsvUnicodeReader":
        """fonction utiise pour rendre la classe iterable """
        while self.line < self.ligne_saut:
            self.line += 1
            self.row = next(self.reader)
        self.line += 1
        self.logger.debug("ligne: %s", self.line)
        self.row = next(self.reader)
        self.logger.debug("ligne: %s", self.row)
        self.frais = decimal.Decimal(0)
        return self

    def __iter__(self) -> "CsvUnicodeReader":
        """fonction utiise pour rendre la classe iterable """
        return self

    @property
    def detail(self) -> str:
        """retourne le champ detail"""
        return self.row[self.champ_detail].strip()

    def in_detail(self, regxp: str, champ: str = "") -> t.Union[t.List[str], str, None]:
        """ fonction qui cherche danc champs la regexp re .
        si ne seule reponse la renvoie sinon renvoie une liste
        @param champ: lieu de la recherche
        @param regxp: regexp a chercher
        @return array or string
        """

        if not champ:
            champ = self.row[self.champ_detail]
        else:
            champ = self.row[champ]
        texte = re.findall(regxp, champ, re.UNICODE | re.IGNORECASE)
        if not texte:
            return None
        else:
            if len(texte) == 1:
                return texte[0]
            else:
                return texte


def uuid() -> str:  # pragma: no cover
    """raccourci vers uuid4"""
    return str(uuid4())


def is_iterable(obj: t.Any) -> bool:
    return isinstance(obj, Iterable)


class UtilsException(Exception):
    """une classe exception qui permet d'afficher tranquillement ce que l'on veut"""

    def __init__(self, message: str) -> None:
        """

        @param message: le message qui est evnoye par l'exception
        @type message: str
        """
        super().__init__(message)
        self.msg = message

    def __str__(self) -> str:
        return self.msg

    def __repr__(self) -> str:
        return self.__str__()


class FormatException(UtilsException):
    pass


def strpdate(var: t.Any, fmt: str = "%Y-%m-%d") -> datetime.date:
    """ renvoie la date
        @param var: variable d'entree
        @type var: date or datetime or string
        @param fmt: format de la date, par defaut "%Y-%m-%d"
        @type fmt: str
        @return datetime.date
        @raise FormatException: si s n'est pas une date
        """
    try:
        if isinstance(var, datetime.datetime):
            return datetime.date(var.year, var.month, var.day)
        if isinstance(var, datetime.date):
            # noinspection PyTypeChecker
            return var
        var = "%s" % var
        end_date = time.strptime(var, fmt)
        return datetime.date(end_date.tm_year, end_date.tm_mon, end_date.tm_mday)
    except ValueError:
        raise FormatException('"%s" n\'est pas est une date' % var)


def is_date(var: t.Any, fmt: str = "%Y-%m-%d") -> bool:
    """ fonction qui renvoie True si c'est une date
        @param var: whatever
        @param fmt: format de la date, par defaut "%Y-%m-%d"
        @return bool """
    try:
        ok = bool(strpdate(var, fmt))  # pylint: disable= W0612
    except FormatException:
        ok = False
    return ok


def to_decimal(s: t.Any, thousand_point: bool = False, virgule: bool = True, space: bool = True) -> decimal.Decimal:
    """fonction qui renvoie un decimal en partant d'un nombre francais
        @param s: string representqnt le decimal
        @param thousand_point: si TRUE utilise le point comme separateur de milliers sinon pas de separateur
        @param virgule: si true, utilise la virgule comme separateur decimal sinon utilisation du point
        @param space: si true utilise l'espace comme separateur de millier sinon pas de separateur
        @return decimal"""
    if not s:
        return decimal.Decimal("0")
    if thousand_point is True and virgule is False:
        raise RuntimeError("pas possible d'avoir les deux thousand_point et virgule")
    s = str(s).strip()
    if thousand_point:
        s = s.replace(".", "")
    if virgule:
        s = s.replace(",", ".")
    if space:
        s = s.replace(" ", "")
    retour = decimal.Decimal(s)
    return retour


def is_number(s: t.Any) -> bool:
    """fonction qui verifie si ca a l'apparence d'un nombre
    @param s: whatever
    @return bool"""
    try:
        n = float(s)  # for int, long and float
        if math.isnan(n) or math.isinf(n):
            return False
    except ValueError:
        try:
            complex(s)  # for complex
        except ValueError:
            return False
    return True


def datetostr(d: t.Union[None, datetime.date], defaut: str = "0/0/0", param: str = "%d/%m/%Y", gsb: bool = False) -> str:
    """
    fonction qui transforme un object date en une chaine AA/MM/JJJJ
    @param s:objet date
    @param defaut: format a transformer, par defaut c'est AA/MM/JJJJ
    @param gsb: enleve les 0 en debut de jour et mois
    """
    if d is None:
        return defaut
    else:
        if isinstance(d, datetime.date):
            # noinspection PyArgumentList
            s = d.strftime(param)
            if gsb:
                result = []
                tab = s.split("/")
                for partie in tab:
                    if partie[0] == "0":  # transform 01/01/2010 en 1/1/2010
                        partie = partie[1:]
                    result.append(partie)
                return "/".join(result)
            else:
                return s
        else:
            raise FormatException("attention ce ne peut pas etre qu'un objet date et c'est un %s (%s)" % (type(d), d))


def force_text(s: t.Any) -> str:
    return "%s" % s


def booltostr(s: t.Any, defaut: str = "0") -> str:
    """format un bool en 0 ou 1 avec gestion des null et gestion des 0 sous forme de chaine de caractere
    @param s:objet bool
    @param defaut: string par defaut pour les none
    """
    if s is None:
        return defaut
    else:
        if isinstance(s, bool):
            # c'est ici le principe
            return force_text(int(s))
        try:
            i = int("%s" % s)
            if not i:
                return "0"
            else:
                return "1"
        except ValueError:
            return force_text(int(bool(s)))


def floattostr(f: t.Optional[float], nb_digit: int = 7) -> str:
    """ convertit un float en string 10,7"""
    s = "{0:0.{1}f}".format(f, nb_digit)
    return s.replace(".", ",").strip()


def typetostr(liste: t.List, s: str, defaut: str = "0") -> str:
    """convertit un indice d'une liste par une string
    @param liste: liste a utiliser
    @param s: string comprenand le truc a chercher dans la liste
    @param defaut: reponse par defaut si None"""
    liste = [force_text(b[0]) for b in liste]
    try:
        s = force_text(liste.index(s) + 1)
    except ValueError:  # on a un cas à defaut
        s = defaut
    return s


# trucs commun pour beancount


NoneType = type(None)
bc_directives = t.Union[
    data.Open,
    data.Close,
    data.Commodity,
    data.Balance,
    data.Pad,
    data.Transaction,
    data.Note,
    data.Event,
    data.Query,
    data.Price,
    data.Document,
    data.Custom,
]


def printer_entries(entries: t.Sequence[bc_directives], filename: str) -> None:
    previous_type = type(entries[0]) if entries else None
    eprinter = printer.EntryPrinter(dcontext=None, render_weight=False)
    with open(filename, mode="w", encoding="utf-8") as file:
        for entry in entries:
            entry_type = type(entry)
            if not isinstance(entry, (data.Close, data.Open)):
                if isinstance(entry, (data.Transaction, data.Commodity)) or entry_type is not previous_type:
                    file.write("\n")
            previous_type = entry_type
            string = print_entry(entry, eprinter)
            file.write(string)


def print_entry(entry: bc_directives, eprinter: printer.EntryPrinter = None) -> str:
    if not eprinter:
        eprinter = printer.EntryPrinter(dcontext=None, render_weight=False)
    return "\n".join([ligne.rstrip() for ligne in eprinter(entry).split("\n")])


def check_before_add(entry: data.Transaction) -> None:
    log = logging.getLogger("Main")
    try:
        data.sanity_check_types(entry)
        for posting in entry.postings:
            if posting.account is None:
                raise AssertionError("problem")
        if len(entry.postings) == 0:
            raise AssertionError("problem")
    except AssertionError as exp:
        log.error(
            "error , problem assertion %s in the transaction %s", pprint.pformat(exp), pprint.pformat(entry),
        )


def load_bc_file(filename: str, debug=False) -> t.List[bc_directives]:
    if debug:
        logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
        log = logging.getLogger("load_bc")
    # creation de la structure qui va recevoir
    error_io = StringIO()
    entries, errors, options_map = loader.load_file(filename, log_errors=error_io)
    if debug:
        log.info(f"loading '{filename}'")
        for err in errors:
            log.warning("{} {}".format(printer.render_source(err.source), err.message))
    if errors:
        raise UtilsException("des erreurs existent dans le fichier beancount")
    return entries
