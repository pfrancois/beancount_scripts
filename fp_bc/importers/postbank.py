# coding=utf-8

import datetime
import logging
import re
from os import path
import pprint


from beancount.core import amount
from beancount.core import data  # pylint:disable=E0611
from beancount.core import flags
from beancount.core.number import MISSING
from beancount.ingest import importer

from fp_bc.utils import CsvUnicodeReader
from fp_bc import utils

# import typing as t

NoneType = type(None)


class ImporterPB(importer.ImporterProtocol):
    def __init__(
        self, tiers_update, tiers_cat, currency, account_root, account_cash, cat_default, cat_frais
    ):
        self.tiers_update = tiers_update
        self.tiers_cat = tiers_cat
        self.logger = logging.getLogger(__file__)  # pylint: disable=W0612
        self.currency = currency
        self.account_root = account_root
        self.account_cash = account_cash
        self.cat_default = cat_default
        self.cat_frais = cat_frais

        regex = (
            re.compile(
                r"Referenz (?:VZ)?\d+(?: \d+)? Mandat (?:\d+|OFFLINE) Einreicher-ID \S\S\w+ (?P<desc>(?P<tiers>.+?)//?.+/.+(?: Terminal \d+)? (?P<date>\d\d\d\d-\d\d-\d\d)T\d\d:\d\d:\d\d (?:Folgenr.|Verfalld.) \d+(?: Entgelt (?P<frais>\d+,\d+) EUR)?)"
            ),
            re.compile(
                r"(PGA|KBS) \d+ KRT\d+/\d\d.\d\d (?P<desc>(?P<date>\d\d.\d\d) \d\d.\d\d TA-NR. \d+ \d+ .*)"
            ),
            re.compile(r"ABRECHNUNG VOM (?P<date>\d\d.\d\d.\d\d)"),
            re.compile(
                r"Referenz .* Mandat .+ Einreicher-ID \w+ (?P<desc>.*?) \S\S\S\d+ (?P<date>\d\d.\d\d)"
            ),
        )
        self.corr = {
            "retrait": (("Auszahlung"), regex[1]),
            "retrait_avec_frais": (
                ("Bargeldausz. GA Ausland", "Auszahlung Geldautomat", "Bargeldausz. Geldautomat"),
                regex[0],
            ),
            "Virement automatique": (("Dauerauftrag",), None),
            "Virement_recu": (("Gutschrift",), None),
            "vpay": (("Kartenzahlung",), regex[0]),
            "Carte Visa": (("Kreditkartenumsatz",), regex[2]),
            "interets": (("Zinsen", "Zinsen/Entgelt"), regex[0]),
            "prelevement": (("Lastschrift",), regex[3]),
            "placement": (("Umbuchung",), regex[0]),
            "impots": (("KapSt",), regex[0]),
            "Virement": (("Überweisung", "Übertrag", "Überweisung neutral"), None),
        }

    def identify(self, file):
        return re.match(
            r"PB_Umsatzauskunft_KtoNr\d+_\d\d-\d\d-\d\d\d\d_\d\d\d\d.csv", path.basename(file.name)
        )

    def file_account(self, _):
        return self.account_root

    def cat(self, tiers):
        for regle_cat in self.tiers_cat:
            if re.findall(regle_cat[0], tiers, re.UNICODE | re.IGNORECASE):
                return regle_cat[1]
        return self.cat_default

    def tiers_update_verifie(self, tiers):
        for regle_tiers in self.tiers_update:
            if re.search(regle_tiers[0], tiers, re.UNICODE | re.IGNORECASE):
                tiers = regle_tiers[1]
        return tiers

    def check_before_add(self, entry):
        try:
            data.sanity_check_types(entry)
            for posting in entry.postings:
                if posting.account is None:
                    raise AssertionError("problem")
        except AssertionError as exp:
            self.logger.error(
                "error , problem assertion %s in the tranaction %s",
                pprint.pformat(exp),
                pprint.pformat(entry),
            )

    def extract(self, file, existing_entries=None):
        # Open the CSV file and create directives.
        entries = []
        error = False
        with open(file.name, "r", encoding="windows-1250") as fichier:
            for index, row in enumerate(
                CsvUnicodeReader(
                    fichier,
                    champs=[
                        "date",
                        "valeur",
                        "moyen",
                        "detail",
                        "autorite",
                        "tiers",
                        "montant",
                        "solde",
                    ],
                    ligne_saut=8,
                    champ_detail="detail",
                ),
                9,
            ):
                # index est le numero de ligne
                # row est la ligne.
                moyen_ok = False
                moyen = MISSING
                regex = MISSING
                for nom_moyen, regle_moyen in self.corr.items():
                    if row.row["moyen"] in regle_moyen[0]:
                        moyen = nom_moyen
                        regex = regle_moyen[1]
                if moyen == MISSING:
                    error = True
                    self.logger.error(
                        "attention , moyen %s inconnu pour operation ligne %s",
                        row.row["moyen"],
                        index,
                    )
                tiers = None
                meta = data.new_metadata(file.name, index)
                meta["comment"] = row.detail.strip()
                meta["source"] = "Postank csv"
                nombre = utils.to_decimal(row.row["montant"][:-1], thousand_point=True)
                posting_1 = data.Posting(
                    account=self.account_root,
                    units=amount.Amount(nombre, self.currency),
                    cost=None,
                    flag=None,
                    meta=None,
                    price=None,
                )
                if moyen == "retrait":
                    moyen_ok = True
                    flag = flags.FLAG_TRANSFER
                    retour = regex.match(row.detail)
                    if retour:
                        annee = utils.strpdate(
                            row.row["date"], "%d.%m.%Y"
                        ).year  # si on est en janvier , les depenses sont celles de decembre
                        if utils.strpdate(row.row["date"], "%d.%m.%Y").month == 1:
                            annee -= 1
                        date = utils.strpdate(f"{retour.group('date')}.{annee}", "%d.%m.%Y")
                        desc = retour.group("desc")
                    else:
                        error = True
                        self.logger.error(
                            "attention , probleme regex dans pb pour operation ligne %s", index
                        )
                        continue
                    tiers = "Virement"
                    posting_2 = data.Posting(
                        account=self.account_cash,
                        units=amount.Amount(nombre * -1, self.currency),
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    transac = data.Transaction(
                        meta=meta,
                        date=date,
                        flag=flag,
                        payee=tiers,
                        narration="",
                        tags=data.EMPTY_SET,
                        links=data.EMPTY_SET,
                        postings=[posting_1, posting_2],
                    )
                    self.check_before_add(transac)
                    entries.append(transac)
                if moyen == "retrait_avec_frais":
                    moyen_ok = True
                    flag = flags.FLAG_TRANSFER
                    retour = regex.match(row.detail)
                    if retour:
                        annee = utils.strpdate(
                            row.row["date"], "%d.%m.%Y"
                        ).year  # si on est en janvier , les depenses sont celles de decembre
                        if utils.strpdate(row.row["date"], "%d.%m.%Y").month == 1:
                            annee -= 1
                        date = utils.strpdate(retour.group("date"), "%Y-%m-%d")
                        desc = retour.group("desc")
                    else:
                        error = True
                        self.logger.error(
                            "attention , probleme regex pour operation ligne %s", index
                        )
                        continue
                    tiers = "Virement"
                    try:
                        frais = utils.to_decimal(retour.group("frais"), thousand_point=True) * -1
                        nombre_sans_frais = nombre - frais
                        posting_2 = data.Posting(
                            account=self.account_cash,
                            units=amount.Amount(nombre_sans_frais * -1, self.currency),
                            cost=None,
                            flag=None,
                            meta=None,
                            price=None,
                        )
                        if frais:
                            posting_3 = data.Posting(
                                account=self.cat_frais,
                                units=amount.Amount(frais * -1, self.currency),
                                cost=None,
                                flag=None,
                                meta=None,
                                price=None,
                            )
                            transac = data.Transaction(
                                meta=meta,
                                date=date,
                                flag=flag,
                                payee=tiers,
                                narration="",
                                tags=data.EMPTY_SET,
                                links=data.EMPTY_SET,
                                postings=[posting_1, posting_2, posting_3],
                            )
                        else:
                            transac = data.Transaction(
                                meta=meta,
                                date=date,
                                flag=flag,
                                payee=tiers,
                                narration="",
                                tags=data.EMPTY_SET,
                                links=data.EMPTY_SET,
                                postings=[posting_1, posting_2],
                            )
                    except IndexError:
                        posting_2 = data.Posting(
                            account=self.account_cash,
                            units=amount.Amount(nombre * -1, self.currency),
                            cost=None,
                            flag=None,
                            meta=None,
                            price=None,
                        )
                        transac = data.Transaction(
                            meta=meta,
                            date=date,
                            flag=flag,
                            payee=tiers,
                            narration="",
                            tags=data.EMPTY_SET,
                            links=data.EMPTY_SET,
                            postings=[posting_1, posting_2],
                        )
                    entries.append(transac)
                if moyen == "Virement automatique":
                    moyen_ok = True
                    flag = flags.FLAG_WARNING
                    date = utils.strpdate(row.row["date"], "%d.%m.%Y")
                    desc = row.row["detail"]
                    tiers = self.tiers_update_verifie(row.row["tiers"])
                    cpt2 = self.cat(tiers)
                    posting_2 = data.Posting(
                        account=cpt2,
                        units=amount.Amount(nombre * -1, self.currency),
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    transac = data.Transaction(
                        meta=meta,
                        date=date,
                        flag=flag,
                        payee=tiers,
                        narration="",
                        tags=data.EMPTY_SET,
                        links=data.EMPTY_SET,
                        postings=[posting_1, posting_2],
                    )
                    self.check_before_add(transac)
                    entries.append(transac)
                if moyen == "Virement_recu":
                    moyen_ok = True
                    flag = flags.FLAG_WARNING
                    date = utils.strpdate(row.row["date"], "%d.%m.%Y")
                    desc = row.row["detail"]
                    tiers = self.tiers_update_verifie(row.row["autorite"])
                    cpt2 = self.cat(tiers)
                    posting_2 = data.Posting(
                        account=cpt2,
                        units=amount.Amount(nombre * -1, self.currency),
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    transac = data.Transaction(
                        meta=meta,
                        date=date,
                        flag=flag,
                        payee=tiers,
                        narration="",
                        tags=data.EMPTY_SET,
                        links=data.EMPTY_SET,
                        postings=[posting_1, posting_2],
                    )
                    self.check_before_add(transac)
                    entries.append(transac)
                if moyen == "vpay":
                    moyen_ok = True
                    flag = flags.FLAG_WARNING
                    retour = regex.match(row.detail)
                    if retour:
                        annee = utils.strpdate(
                            row.row["date"], "%d.%m.%Y"
                        ).year  # si on est en janvier , les depenses sont celles de decembre
                        if utils.strpdate(row.row["date"], "%d.%m.%Y").month == 1:
                            annee -= 1
                        date = utils.strpdate(retour.group("date"), "%Y-%m-%d")
                        tiers = self.tiers_update_verifie(retour.group("tiers"))
                        desc = retour.group("desc")
                    else:
                        error = True
                        self.logger.error(
                            "attention , probleme regex pour operation ligne %s", index
                        )
                        continue
                    cpt2 = self.cat(tiers)
                    try:
                        frais = utils.to_decimal(retour.group("frais"), thousand_point=True) * -1
                        nombre_sans_frais = nombre - frais
                        posting_2 = data.Posting(
                            account=cpt2,
                            units=amount.Amount(nombre_sans_frais * -1, self.currency),
                            cost=None,
                            flag=None,
                            meta=None,
                            price=None,
                        )
                        if frais:
                            posting_3 = data.Posting(
                                account=self.cat_frais,
                                units=amount.Amount(frais, self.currency),
                                cost=None,
                                flag=None,
                                meta=None,
                                price=None,
                            )
                            transac = data.Transaction(
                                meta=meta,
                                date=date,
                                flag=flag,
                                payee=tiers,
                                narration="",
                                tags=data.EMPTY_SET,
                                links=data.EMPTY_SET,
                                postings=[posting_1, posting_2, posting_3],
                            )
                        else:
                            transac = data.Transaction(
                                meta=meta,
                                date=date,
                                flag=flag,
                                payee=tiers,
                                narration="",
                                tags=data.EMPTY_SET,
                                links=data.EMPTY_SET,
                                postings=[posting_1, posting_2],
                            )
                    except IndexError:
                        posting_2 = data.Posting(
                            account=cpt2,
                            units=amount.Amount(nombre * -1, self.currency),
                            cost=None,
                            flag=None,
                            meta=None,
                            price=None,
                        )
                        transac = data.Transaction(
                            meta=meta,
                            date=date,
                            flag=flag,
                            payee=tiers,
                            narration="",
                            tags=data.EMPTY_SET,
                            links=data.EMPTY_SET,
                            postings=[posting_1, posting_2],
                        )
                    self.check_before_add(transac)
                    entries.append(transac)
                if moyen == "Carte Visa":
                    moyen_ok = True
                    flag = flags.FLAG_WARNING
                    date = utils.strpdate(row.row["date"], "%d.%m.%Y")
                    date_visa = MISSING
                    desc = row.detail
                    retour = regex.match(row.detail)
                    if retour:
                        date_visa = utils.strpdate(f"{retour.group('date')}", "%d.%m.%y")
                    else:
                        error = True
                        self.logger.error(
                            "attention , probleme regex pour operation ligne %s", index
                        )
                        continue
                    tiers = "Virement"
                    posting_2 = data.Posting(
                        account="Assets:Banque:Postbank-Visa",
                        units=amount.Amount(nombre * -1, self.currency),
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    transac = data.Transaction(
                        meta=meta,
                        date=date,
                        flag=flag,
                        payee=tiers,
                        narration="",
                        tags=data.EMPTY_SET,
                        links=data.EMPTY_SET,
                        postings=[posting_1, posting_2],
                    )
                    self.check_before_add(transac)
                    entries.append(transac)
                    entries.append(
                        data.Balance(
                            meta,
                            date_visa + datetime.timedelta(days=1),
                            "Assets:Banque:Postbank-Visa",
                            amount.Amount(nombre, self.currency),
                            None,
                            None,
                        )
                    )
                if moyen == "interets":
                    moyen_ok = True
                    date = utils.strpdate(row.row["date"], "%d.%m.%Y")
                    flag = flags.FLAG_WARNING
                    tiers = "Postbank"
                    desc = "interets"
                    posting_2 = data.Posting(
                        account=self.cat_frais,
                        units=amount.Amount(nombre * -1, self.currency),
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    transac = data.Transaction(
                        meta=meta,
                        date=date,
                        flag=flag,
                        payee=tiers,
                        narration=desc,
                        tags=data.EMPTY_SET,
                        links=data.EMPTY_SET,
                        postings=[posting_1, posting_2],
                    )
                    self.check_before_add(transac)
                    entries.append(transac)
                if moyen == "prelevement":
                    moyen_ok = True
                    date = utils.strpdate(row.row["date"], "%d.%m.%Y")
                    flag = flags.FLAG_WARNING
                    tiers = self.tiers_update_verifie(row.row["tiers"])
                    cpt2 = self.cat(tiers)
                    retour = regex.match(row.detail)
                    desc = ""
                    if retour:
                        desc = retour.group("desc")
                    else:
                        error = True
                        self.logger.error(
                            "attention , probleme regex pour operation ligne %s", index
                        )
                        continue
                    posting_2 = data.Posting(
                        account=cpt2,
                        units=amount.Amount(nombre * -1, self.currency),
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    transac = data.Transaction(
                        meta=meta,
                        date=date,
                        flag=flag,
                        payee=tiers,
                        narration="",
                        tags=data.EMPTY_SET,
                        links=data.EMPTY_SET,
                        postings=[posting_1, posting_2],
                    )
                    self.check_before_add(transac)
                    entries.append(transac)
                if moyen == "Virement":
                    moyen_ok = True
                    date = utils.strpdate(row.row["date"], "%d.%m.%Y")
                    flag = flags.FLAG_WARNING
                    tiers = self.tiers_update_verifie(row.row["autorite"])
                    cpt2 = self.cat(tiers)
                    desc = row.detail
                    posting_2 = data.Posting(
                        account=cpt2,
                        units=amount.Amount(nombre * -1, self.currency),
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    transac = data.Transaction(
                        meta=meta,
                        date=date,
                        flag=flag,
                        payee=tiers,
                        narration="",
                        tags=data.EMPTY_SET,
                        links=data.EMPTY_SET,
                        postings=[posting_1, posting_2],
                    )
                    self.check_before_add(transac)
                    entries.append(transac)
                if not moyen_ok:
                    error = True
                    self.logger.error("moyen %s non implementé", moyen)
        with open(file.name, "r", encoding="windows-1250") as fichier:
            for index, row in enumerate(
                CsvUnicodeReader(
                    fichier, champs=["name", "valeur"], ligne_saut=5, champ_detail="detail"
                ),
                6,
            ):
                date = utils.strpdate(
                    re.findall(
                        r"PB_Umsatzauskunft_KtoNr\d+_(\d\d-\d\d-\d\d\d\d)_\d+.csv",
                        fichier.name,
                        re.UNICODE | re.IGNORECASE,
                    )[0].strip(),
                    "%d-%m-%Y",
                )
                montant = utils.to_decimal(row.row["valeur"][:-2], thousand_point=True)
                meta = data.new_metadata(file.name, 1)
                entries.append(
                    data.Balance(
                        meta,
                        date + datetime.timedelta(days=1),
                        self.account_root,
                        amount.Amount(montant, self.currency),
                        None,
                        None,
                    )
                )
                break
        if not error:
            return entries
        else:
            return None
