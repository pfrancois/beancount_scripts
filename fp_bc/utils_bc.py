from io import StringIO
import typing as t
import logging
import pprint
from beancount import loader
from beancount.core import data  # pylint:disable=E0611
from beancount.parser import printer

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


def print_entry(entry: bc_directives, eprinter: t.Optional[printer.EntryPrinter] = None) -> str:
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


def load_bc_file(filename: str, debug: bool = False) -> t.Tuple[t.List[bc_directives], t.List[t.NamedTuple]]:
    log = logging.getLogger("load_bc")
    # creation de la structure qui va recevoir
    error_io = StringIO()
    entries, errors, options_map = loader.load_file(filename, log_errors=error_io)
    if debug:
        log.info(f"loading '{filename}'")
        for err in errors:
            log.warning("{} {}".format(printer.render_source(err.source), err.message))
    if errors:
        raise utils.UtilsException("des erreurs existent dans le fichier beancount")
    return (entries, options_map)
