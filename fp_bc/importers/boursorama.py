# coding=utf-8
import logging
import re
from os import path
import pprint
import decimal
import typing as t
import datetime  # noqa

from beancount.core import amount
from beancount.core import account
from beancount.core import data  # pylint:disable=E0611
from beancount.core import flags
from beancount.ingest import importer  # noqa
from beancount.ingest import cache

from fp_bc.utils import CsvUnicodeReader
from fp_bc import utils


__version__ = "1.1.0"
# ajout des types


def short(account_name: str) -> str:
    if account.leaf(account_name) == "Caisse":
        return "Caisse"
    if account.leaf(account_name) == "Cash":
        return ":".join(account_name.split(":")[-2:])
    if account_name.split(":")[0] in ("Expenses", "Income", "Equity"):
        return ":".join(account_name.split(":")[1:])
    return account.leaf(account_name)


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
    data.Custom
]


class ImporterBoursorama(importer.ImporterProtocol):
    def __init__(
        self,
        tiers_update: t.Sequence[t.Sequence[str]],
        tiers_cat: t.Sequence[t.Sequence[str]],
        currency: str,
        account_root: str,
        account_cash: t.Union[str, NoneType],
        cat_default: str,
        account_visa: t.Union[str, NoneType],
        account_id: str,
    ) -> None:
        self.tiers_update = tiers_update
        self.tiers_cat = tiers_cat
        self.logger = logging.getLogger(__file__)  # pylint: disable=W0612
        self.currency = currency
        self.account_root = account_root
        self.account_cash = account_cash  # si none, pas de gestion du cash, on met tout en non affecte
        self.cat_default = cat_default
        self.account_visa = account_visa  # si none pas de gestion d'un compte separé visa
        self.account_id = account_id

    def name(self) -> str:
        # permet d'avoir deux comptess bourso et de pouvoir les differenciers au niveau de la config
        return "{}.{}".format(self.__class__.__name__, self.account_id)

    def identify(self, file: t.IO) -> bool:  # type: ignore[override]
        if bool(re.match(r"export-operations-\d\d-\d\d-\d\d\d\d.*.csv", path.basename(file.name))):
            return True
        else:
            return False

    def file_account(self, _: t.IO) -> str:  # type: ignore[override]
        return self.account_root

    def check_before_add(self, entry: data.Transaction) -> None:
        try:
            data.sanity_check_types(entry)
            for posting in entry.postings:
                if posting.account is None:
                    raise AssertionError("problem")
        except AssertionError as exp:
            self.logger.error(f"error , problem assertion {pprint.pformat(exp)} in the transaction {pprint.pformat(entry)}")

    def cat(self, tiers: str) -> str:
        for regle_cat in self.tiers_cat:
            if re.search(regle_cat[0], tiers, re.UNICODE | re.IGNORECASE):
                return regle_cat[1]
        return self.cat_default

    def tiers_update_verifie(self, tiers: str) -> str:
        for regle_tiers in self.tiers_update:
            if re.search(regle_tiers[0], tiers, re.UNICODE | re.IGNORECASE):
                tiers = regle_tiers[1]
        else:
            tiers = tiers.capitalize()
        return tiers

    def extract(self, file: t.IO, existing_entries: t.Optional[t.List[bc_directives]] = None) -> t.List[bc_directives]:  # type: ignore[override]
        # Open the CSV file and create directives.
        entries: t.List[bc_directives] = []
        error = False
        with open(file.name, "r", encoding="windows-1252") as fichier:
            for index, row in enumerate(
                CsvUnicodeReader(
                    fichier,
                    champs=[
                        "dateOp",
                        "dateVal",
                        "label",
                        "category",
                        "categoryParent",
                        "amount",
                        "comment",
                        "accountNum",
                        "accountLabel",
                        "accountbalance",
                    ],
                    ligne_saut=2,
                    champ_detail="label",
                ),
                4,
            ):
                tiers = None
                cpt2 = None
                narration = ""
                meta = data.new_metadata(file.name, index)
                # pas besoin de cheque
                meta["comment"] = row.detail.strip()
                flag = None
                try:
                    montant_releve = amount.Amount(utils.to_decimal(row.row["amount"]), self.currency)
                except decimal.InvalidOperation:
                    error = True
                    self.logger.error(f"montant '{row.row['amount']}' invalide pour operation ligne {index}")
                    continue
                date_releve = utils.strpdate(row.row["dateOp"])
                number = montant_releve.number
                if number is None:
                    number = decimal.Decimal("0")
                # virement interne
                if "VIR SEPA MR FRANCOIS PEGORY" in row.detail:
                    cpt2 = "Assets:Banque:SG"
                if cpt2:  # VIREMENT interne
                    posting_1 = data.Posting(
                        account=self.account_root,
                        units=montant_releve,
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    posting_2 = data.Posting(
                        account=cpt2,
                        units=amount.Amount(number * decimal.Decimal("-1"), self.currency),
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    tiers = "Virement"
                    if number < 0:
                        narration = "%s => %s" % (short(self.account_root), short(cpt2))
                    else:
                        narration = "%s => %s" % (short(cpt2), short(self.account_root))
                    links = data.EMPTY_SET
                    transac = data.Transaction(
                        meta=meta,
                        date=date_releve,
                        flag=flags.FLAG_WARNING,
                        payee=tiers.strip(),
                        narration=narration,
                        tags=data.EMPTY_SET,
                        links=links,
                        postings=[posting_1, posting_2],
                    )
                    self.check_before_add(transac)
                    entries.append(transac)
                    continue
                # paiment carte visa
                if row.in_detail(r"^CARTE (?P<date>\d\d\/\d\d\/\d\d)"):  # cas general de la visa
                    flag = flags.FLAG_WARNING
                    reg_visa = r"^CARTE (?P<date>\d\d\/\d\d\/\d\d)\s(?P<desc>.*)(?:\d\sCB|\sCB)\*1203"
                    retour = re.search(reg_visa, row.detail, re.UNICODE | re.IGNORECASE)
                    if retour:
                        tiers = retour.group("desc").strip()
                        date_visa = utils.strpdate(f"{retour.group('date')[0:5]}/20{retour.group('date')[6:8]}", "%d/%m/%Y")
                        if not tiers:
                            error = True
                            self.logger.error("attention , probleme regex visa pour operation ligne %s", index)
                            continue
                    else:
                        error = True
                        self.logger.error("attention , probleme regex visa pour operation ligne %s", index)
                        self.logger.error(f"{row.detail}")
                        continue
                    if self.account_visa:
                        posting_1 = data.Posting(
                            account=self.account_visa,
                            units=montant_releve,
                            cost=None,
                            flag=None,
                            meta=None,
                            price=None,
                        )
                    else:
                        posting_1 = data.Posting(
                            account=self.account_root,
                            units=montant_releve,
                            cost=None,
                            flag=None,
                            meta=None,
                            price=None,
                        )
                    tiers = self.tiers_update_verifie(tiers).strip()

                    cpt2 = self.cat(tiers)
                    posting_2 = data.Posting(
                        account=cpt2,
                        units=amount.Amount(number * -1, self.currency),
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    transac = data.Transaction(
                        meta=meta,
                        date=date_visa,
                        flag=flag,
                        payee=tiers,
                        narration="",
                        tags=data.EMPTY_SET,
                        links=data.EMPTY_SET,
                        postings=[posting_1, posting_2],
                    )
                    self.check_before_add(transac)
                    entries.append(transac)
                    continue
                else:
                    self.logger.error("type inconnu ligne %s", index)
            if error:
                raise Exception("au moins une erreur")
        return entries
