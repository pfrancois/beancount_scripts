from io import StringIO
import typing as t
import logging
import pprint
import datetime
import re

from beancount import loader
from beancount.core import data  # pylint:disable=E0611
from beancount.parser import printer
from beancount.core import getters
import beancount.core.account as core_account
from beancount.core import number

from decimal import Decimal

from . import utils

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
    entries = sort(entries)
    previous_type = type(entries[0])
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


def print_entry(entry: bc_directives, eprinter: t.Optional[printer.EntryPrinter] = None) -> str:
    if not eprinter:
        eprinter = printer.EntryPrinter(dcontext=None, render_weight=False)
    sortie_txt = "\n".join([ligne.rstrip() for ligne in eprinter(entry).split("\n")])
    final = re.sub(r'\s*None EUR', '', sortie_txt)
    return final


def check_before_add(entry: data.Transaction, raise_exception: t.Optional[bool] = None) -> None:
    log = logging.getLogger("Main")
    if raise_exception is None:
        if log.getEffectiveLevel() == logging.DEBUG:
            raise_exception = True
        else:
            raise_exception = False
    try:
        data.sanity_check_types(entry)
        for posting in entry.postings:
            if posting.account is None:
                raise AssertionError("problem")
        if len(entry.postings) == 0:
            raise AssertionError("problem")
    except AssertionError as exp:
        if raise_exception:
            raise utils.UtilsException(f"error , problem assertion {pprint.pformat(exp)} in the transaction {pprint.pformat(entry)}")
        else:
            log.error(
                "error , problem assertion %s in the transaction %s",
                pprint.pformat(exp),
                pprint.pformat(entry),
            )


def load_bc_file(filename: str, debug: bool = False, skip_error: bool = False) -> t.Tuple[t.List[bc_directives], t.List[t.NamedTuple]]:
    log = logging.getLogger("load_bc")
    # creation de la structure qui va recevoir
    error_io = StringIO()
    entries, errors, options_map = loader.load_file(filename, log_errors=error_io)
    if skip_error:
        if debug:
            log.info(f"loading '{filename}'")
            for err in errors:
                log.warning("{} {}".format(printer.render_source(err.source), err.message))
        if errors:
            raise utils.UtilsException("des erreurs existent dans le fichier beancount")
    return (entries, options_map)


def short(account_name: str) -> str:
    """renvoie le nom court du compte"""
    if core_account.leaf(account_name) == "Caisse":
        return "Caisse"
    if core_account.leaf(account_name) == "Cash":
        return ":".join(account_name.split(":")[-2:])
    if account_name.split(":")[0] in ("Expenses", "Income", "Equity"):
        return ":".join(account_name.split(":")[1:])
    return core_account.leaf(account_name)


def entry_sort_key(entry: bc_directives) -> t.Tuple[datetime.date, int, str]:
    if isinstance(entry, data.Transaction):
        return (entry.date, 0, f"{entry.payee}:{entry.narration}")
    if isinstance(entry, data.Price):
        return (entry.date, 0, entry.currency)
    if isinstance(entry, data.Open):
        return (utils.strpdate("2000-01-01"), -1, entry.account)
    if isinstance(entry, data.Close):
        return (utils.strpdate("2000-01-01"), -1, entry.account)
    if isinstance(entry, data.Balance):
        return (entry.date, -2, entry.account)
    if isinstance(entry, data.Commodity):
        return (utils.strpdate("2000-01-01"), 0, entry.currency)
    return (entry.date, 0, str(entry.meta["lineno"]))


def sort(liste: t.Sequence[bc_directives]) -> t.List[bc_directives]:
    return sorted(liste, key=entry_sort_key)
