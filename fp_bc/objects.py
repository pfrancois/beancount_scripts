# -*- coding: utf-8 -*-

# coding=utf-8
import logging
import re  # noqa
from pathlib import Path as Path
import os
import sys
from io import StringIO  # noqa
from pprint import pprint  # noqa
import decimal  # noqa
import typing as t
import datetime  # noqa
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd  # noqa

# import numpy as np  # noqa
from beancount.parser import printer

from beancount.core import amount as core_amount  # noqa
from beancount.core import account as core_account  # noqa
from beancount.core import data  # noqa
from beancount.core import flags  # noqa
from beancount.ingest import importer  # noqa
from beancount import loader  # noqa

from fp_bc import utils as utils  # noqa

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s\t%(levelname)s\t%(message)s")
log = logging.getLogger("Main")


def blog(entry_blog: data.Transaction) -> None:
    render = printer.EntryPrinter(dcontext=None, render_weight=False)
    print(f'{entry_blog.meta["filename"]}:{entry_blog.meta["lineno"]}')
    render(entry_blog)


@dataclass
class Posting(object):
    date: datetime.date
    compte_origine: str
    compte_destination: str
    tiers: str
    id_transaction: int
    transfer: bool = False
    desc: str = ""
    montant: t.Optional[Decimal] = None
    cost: t.Optional[Decimal] = None
    nb: t.Optional[Decimal] = None
    prix: t.Optional[Decimal] = None
    ope_titre: t.Optional[bool] = False
    titre: t.Optional[str] = None


@dataclass
class Price(object):
    date: datetime.date
    titre: str
    number: Decimal


class Bc(object):
    def __init__(self, filename: str = "") -> None:
        # chargement du fichier
        self.filename = Path(filename)
        if str != "":
            load = True
            if not self.filename.exists():
                raise OSError(0, "fichier inconnu", os.fspath(self.filename))
            prev_cwd = Path.cwd()
            os.chdir(self.filename.parent)
            try:
                error_io = StringIO()
                self.entries, errors, options_map = loader.load_file(os.fspath(self.filename), log_errors=error_io)
                log.info("loading file")
                for err in errors:
                    log.error("{} {}".format(printer.render_source(err.source), err.message))
                if errors:
                    sys.exit(1)
                log.info("loading ok")
            finally:
                os.chdir(prev_cwd)

        # creations de structures
        self.postings: t.List[Posting] = list()
        self.prices: t.list[Price] = list()
        if load:
            self.prices_load()
            self.postings_load()

    def prices_load(self):
        for entry in self.entries:
            if isinstance(entry, data.Price):
                self.prices.append(Price(date=entry.date, titre=entry.currency, number=entry.amount.number))

    def prices_search(self, date_src: datetime.date, titre: str) -> Decimal:
        for p in self.prices:
            if p.date == date_src and p.titre == titre:
                return p.number
        else:
            raise KeyError(f"prix inconnu pour le titre {titre} à la date du {date_src}")

    def postings_to_df(self) -> pd.DataFrame:
        df = pd.DataFrame(self.postings)
        df["date"] = pd.to_datetime(df["date"])
        df["compte_origine"] = df.compte_origine.astype("string")
        df["compte_destination"] = df.compte_destination.astype("string")
        df["tiers"] = df.tiers.astype("string")
        df["desc"] = df.desc.astype("string")
        df["montant"] = df.montant.astype("float", copy=False)
        df["cost"] = df.cost.astype("float", copy=False)
        df["nb"] = df.nb.astype("float", copy=False)
        df["prix"] = df.prix.astype("float", copy=False)
        df["titre"] = df.titre.astype("string")
        return df

    def load_transac(self, entry: data.Transaction, nb_transaction: int) -> None:
        acc = ""
        transfer = False
        ope_titre_detail: t.Dict[str, t.Dict[str, Decimal]] = dict()
        ope_titre = False
        total_plus_values = 0
        # recupere le compte "bancaire" principale et si c'est un virement ou une ope titre
        for p in entry.postings:
            if core_account.has_component(p.account, "Income") or core_account.has_component(p.account, "Expenses"):
                continue  # pas un virement
            if core_account.has_component(p.account, "Equity"):
                continue
            if p.units.currency != "EUR":
                if core_account.has_component(p.account, "Assets:Titre"):
                    ope_titre = True
                    if acc != p.account:
                        acc = p.account
                    break
                else:
                    raise Exception(f'depense non euro autre que titres: {entry.meta["filename"]}:{entry.meta["lineno"]}')
            else:
                if acc == "":
                    acc = p.account
                else:
                    transfer = True
        # gestion effective de l'import
        for p in entry.postings:
            entree = None
            if not transfer and not ope_titre:  # ope normale
                if acc != p.account:
                    entree = Posting(
                        date=entry.date,
                        compte_origine=acc,
                        compte_destination=p.account,
                        transfer=transfer,
                        tiers=entry.payee,
                        desc=entry.narration,
                        montant=p.units.number * -1,
                        id_transaction=nb_transaction,
                    )
                    self.postings.append(entree)
            if transfer:  # virement
                if acc != p.account:
                    entree = Posting(
                        date=entry.date,
                        compte_origine=acc,
                        compte_destination=p.account,
                        transfer=transfer,
                        tiers=entry.payee,
                        desc=entry.narration,
                        montant=p.units.number,
                        id_transaction=nb_transaction,
                    )
                    self.postings.append(entree)
                    entree = Posting(
                        date=entry.date,
                        compte_origine=p.account,
                        compte_destination=acc,
                        transfer=transfer,
                        tiers=entry.payee,
                        desc=entry.narration,
                        montant=p.units.number * -1,
                        id_transaction=nb_transaction,
                    )
                    self.postings.append(entree)
                else:
                    continue  # on le passe car c'est gere autrement
            if ope_titre:
                if acc != p.account:
                    if core_account.has_component(p.account, "Assets"):
                        # virement jambe 1
                        entree = Posting(
                            date=entry.date,
                            compte_origine=acc,
                            compte_destination=p.account,
                            transfer=True,
                            tiers=entry.payee,
                            desc=entry.narration,
                            montant=p.units.number,
                            ope_titre=False,
                            id_transaction=nb_transaction,
                        )
                        self.postings.append(entree)
                        # virement jambe 2
                        entree = Posting(
                            date=entry.date,
                            compte_origine=p.account,
                            compte_destination=acc,
                            transfer=True,
                            tiers=entry.payee,
                            desc=entry.narration,
                            montant=p.units.number * -1,
                            ope_titre=False,
                            id_transaction=nb_transaction,
                        )
                        self.postings.append(entree)
                    else:
                        if core_account.has_component(p.account, "Income:Revenus-placements:Plus-values"):
                            total_plus_values += p.units.number * -1
                        else:
                            # une depense classique integré dans une ope titre
                            entree = Posting(
                                date=entry.date,
                                compte_origine=acc,
                                compte_destination=p.account,
                                transfer=transfer,
                                tiers=entry.payee,
                                desc=entry.narration,
                                montant=p.units.number * -1,
                                ope_titre=False,
                                id_transaction=nb_transaction,
                            )
                            self.postings.append(entree)
                else:
                    # gestion des vraies ope titres
                    if p.cost is not None:
                        if p.units.currency in ope_titre_detail:
                            ope_titre_detail[p.units.currency]["nb"] += p.units.number
                            ope_titre_detail[p.units.currency]["cost"] += abs(p.cost.number * p.units.number)
                            if ope_titre_detail[p.units.currency]["price"] == 0 and p.price is not None:
                                ope_titre_detail[p.units.currency]["price"] = p.price.number
                            ope_titre_detail[p.units.currency]["montant"] += -1 * p.units.number * ope_titre_detail[p.units.currency]["price"]
                        else:
                            if p.units.number > 0:
                                prix = p.cost.number
                            else:
                                if p.price is not None:
                                    prix = p.price.number
                                else:
                                    try:
                                        prix = self.prices_search(date_src=entry.date, titre=p.units.currency)
                                    except KeyError:
                                        print(f"prix {p.units.currency} date {entry.date} none {p.meta['filename']}:{p.meta['lineno']}")
                                        prix = 0
                            ope_titre_detail[p.units.currency] = {
                                "nb": p.units.number,
                                "cost": abs(p.cost.number * p.units.number),
                                "price": prix,
                                "montant": p.units.number * prix * -1,
                            }
                    else:
                        if acc != p.account:
                            raise Exception(f"cost none {p.meta['filename']}:{p.meta['lineno']}")
        # verification plus values
        pv = sum([(abs(v["montant"]) - abs(v["cost"])) for (k, v) in ope_titre_detail.items()]) * -1
        if abs(abs(pv) - abs(total_plus_values)) > 1:
            # raise Exception(
            # pprint(ope_titre_detail)
            print("----")
            print(f"pour l'operation ligne {entry.meta['lineno']} {pv=} different {total_plus_values=}")
            print(f'{entry.date} {entry.flag} "{entry.payee}" "{entry.narration}" #{" #".join(entry.tags)}')
            flag_vente = False
            for k, v in ope_titre_detail.items():
                if v['nb'] < 0:
                    print(f'  {acc} {v["nb"]} {k} {{}}  @ {v["price"]} EUR')
                    if not flag_vente:
                        print(f'  Income:Revenus-placements:Plus-values')
                        flag_vente = True
                else:
                    print(f'  {acc} {v["nb"]} {k} {{{v["price"]}, {entry.date}}}  @ {v["price"]} EUR')
            print(f'  Expenses:Frais-bancaires  {pv*-1-total_plus_values:.2f} EUR')
            print(f'  {acc}:Cash')
            sys.exit()
        for k, v in ope_titre_detail.items():
            # OST normale
            entree = Posting(
                date=entry.date,
                compte_origine=acc,
                compte_destination="Expenses:OST",
                transfer=False,
                tiers=entry.payee,
                desc=entry.narration,
                montant=v["price"] * v["nb"],
                ope_titre=True,
                id_transaction=nb_transaction,
                nb=v["nb"],
                cost=abs(v["cost"] / v["nb"]),
                titre=k,
                prix=v["price"],
            )
            self.postings.append(entree)
            if v["nb"] < 0:
                entree = Posting(
                    date=entry.date,
                    compte_origine=acc,
                    compte_destination="Income:Revenus-placements:Plus-values",
                    transfer=transfer,
                    tiers=entry.payee,
                    desc=entry.narration,
                    montant=(v["price"] * v["nb"] - v["cost"]) * -1,
                    ope_titre=False,
                    id_transaction=nb_transaction,
                )
                self.postings.append(entree)

    def postings_load(self) -> None:
        nb_err = 0
        for nb, entry in enumerate(data.filter_txns(self.entries)):
            try:
                self.load_transac(entry, nb)
            except Exception as exc:
                lineno = sys.exc_info()[2].tb_next.tb_lineno
                filename = sys.exc_info()[2].tb_next.tb_frame.f_code.co_filename
                nb_err += 1
                print(f"{filename}:{lineno} {exc} pour {entry.meta['filename']}:{entry.meta['lineno']}")
                # sys.exit(1)
        if nb_err:
            print(f"{nb_err} erreurs")

    def entries_to_csv(self, csv_filename):
        df = self.postings_to_df()
        df.to_csv(csv_filename, decimal=",", index=False, sep=";")


filename = "d:/ledger/data/active.ledger"
# filename = "d:/ledger/output/ope_titre.ledger"
bc = Bc(filename=filename)
log.info(f"{len(bc.postings)} postings chargés")
nb = 0
# df = bc.postings_to_df()
bc.entries_to_csv("d:/ledger/output/postings.csv")
