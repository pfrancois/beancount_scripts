# coding=utf-8
import logging
from os import path
import re
import typing as t
import pprint

from beancount.ingest import importer
from beancount.ingest import cache
from fp_bc import utils

import camelot

from beancount.core import amount
from beancount.core import data
from beancount.core import flags
from beancount.core import position


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


class ImporterODDO_PDF(importer.ImporterProtocol):
    def __init__(self) -> None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s   %(levelname)s\t%(message)s", datefmt="%H:%M:%S")
        self.logger = logging.getLogger(__file__)  # pylint: disable=W0612

    def name(self) -> str:
        # permet d'avoir deux comptes et de pouvoir les differenciers au niveau de la config
        return "oddo"

    def identify(self, file: t.IO) -> t.Optional[t.Match[str]]:
        return re.match(f"2021_.*.pdf", path.basename(file.name))

    def file_account(self, _: t.IO) -> str:
        return "Assets:Titre:Generation-vie"

    def check_before_add(self, entry: data.Transaction) -> None:
        try:
            data.sanity_check_types(entry)
            for posting in entry.postings:
                if posting.account is None:
                    raise AssertionError("problem")
        except AssertionError as exp:
            self.logger.error(f"error , problem assertion {pprint.pformat(exp)} in the transaction {pprint.pformat(entry)}")

    def extract(self, file: cache._FileMemo, existing_entries: t.Optional[bc_directives] = None) -> t.List[bc_directives]:
        liste_com = dict()
        for entry in existing_entries:
            if isinstance(entry, data.Commodity):
                if entry.meta.get("isin", ""):
                    liste_com[entry.meta["isin"]] = entry.currency
        self.logger.info('all comodity loaded')
        df = camelot.read_pdf(file, flavor="stream", pages="1,2", strip_text="\n", row_tol=10)[2].df
        montant_global = utils.to_decimal(df.at[1, 6])
        date_min = utils.strpdate("01/01/2030", fmt="%d/%m/%Y")
        achattot = 0
        list_postings = list()
        for i in range(3, len(df) - 1):
            isin = df.loc[i, 2]
            nb = utils.to_decimal(df.loc[i, 3])
            prix = utils.to_decimal(df.loc[i, 4])
            date = utils.strpdate(df.loc[i, 5], fmt="%d/%m/%Y")
            if date_min > date:
                date_min = date
            achattot = achattot + nb * prix
            posting = data.Posting(
                account="Assets:Titre:Generation-vie",
                units=amount.Amount(nb, liste_com[isin]),
                cost=position.Cost(prix, "EUR", date_min, None),
                flag=None,
                meta=None,
                price=amount.Amount(prix, "EUR"),
            )
            list_postings.append(posting)
        self.logger.info(f"{len(list_postings)}")
        list_postings.append(
            data.Posting(
                account="Expenses:Frais-bancaires",
                units=amount.Amount(round(montant_global - achattot, 2), "EUR"),
                cost=None,
                flag=None,
                meta=None,
                price=None,
            )
        )
        list_postings.append(
            data.Posting(
                account="Assets:Titre:Generation-vie:Cash",
                units=amount.Amount(montant_global * -1, "EUR"),
                cost=None,
                flag=None,
                meta=None,
                price=None,
            )
        )
        meta = data.new_metadata("doc", 1)
        transac = data.Transaction(
            meta=meta,
            date=date_min,
            flag=flags.FLAG_WARNING,
            payee="placement",
            narration="",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=list_postings,
        )
        self.logger.info(f"{len(list_postings)}")
        self.check_before_add(transac)
        self.logger.info(pprint.pformat(utils.print_entry(transac)))
        list_e = list()
        list_e.append(transac)
        return list_e
