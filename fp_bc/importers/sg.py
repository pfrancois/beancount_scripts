# coding=utf-8
import logging
import re
from os import path
import pprint
import decimal
import typing as t

from beancount.core import amount
from beancount.core import account
from beancount.core import data  # pylint:disable=E0611
from beancount.core import flags
from beancount.ingest import importer
from beancount.ingest import cache

from fp_bc.utils import CsvUnicodeReader
from fp_bc import utils


__version__ = "2.0.0"


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
    data.Custom,
]


class ImporterSG(importer.ImporterProtocol):
    def __init__(self, currency: str, account_root: str, account_id: str, account_cash: t.Union[str, NoneType], tiers_update: t.List = None) -> None:
        self.logger = logging.getLogger(__file__)  # pylint: disable=W0612
        self.currency = currency
        self.account_root = account_root
        self.account_id = account_id
        self.account_cash = account_cash
        self.tiers_update = tiers_update

    def name(self) -> str:
        # permet d'avoir deux comptes et de pouvoir les differenciers au niveau de la config
        return "{}.{}".format(self.__class__.__name__, self.account_id)

    def identify(self, file: t.IO) -> t.Optional[t.Match[str]]:
        return re.match(f"{self.account_id}.*.csv", path.basename(file.name))

    def file_account(self, _: t.IO) -> str:
        return self.account_root

    def check_before_add(self, entry: data.Transaction) -> None:
        try:
            data.sanity_check_types(entry)
            for posting in entry.postings:
                if posting.account is None:
                    raise AssertionError("problem")
        except AssertionError as exp:
            self.logger.error(f"error , problem assertion {pprint.pformat(exp)} in the transaction {pprint.pformat(entry)}")

    def tiers_update_verifie(self, tiers: str) -> str:
        if self.tiers_update:
            for regle_tiers in self.tiers_update:
                if re.search(regle_tiers[0], tiers, re.UNICODE | re.IGNORECASE):
                    tiers = regle_tiers[1]
        tiers = tiers.capitalize()
        return tiers

    def extract(self, file: cache._FileMemo, existing_entries: t.Optional[bc_directives] = None) -> t.List[bc_directives]:
        # Open the CSV file and create directives.
        entries = []
        error = False
        with open(file.name, "r", encoding="windows-1252") as fichier:
            for index, row in enumerate(
                CsvUnicodeReader(fichier, champs=["date", "libelle", "detail", "montant", "devise"], ligne_saut=2, champ_detail="detail",), 4,
            ):
                tiers = None
                narration = ""
                cpt2 = None
                meta = data.new_metadata(file.name, index)
                meta["comment"] = row.detail.strip()
                flag = flags.FLAG_WARNING
                try:
                    montant_releve = amount.Amount(utils.to_decimal(row.row["montant"]), self.currency)
                except decimal.InvalidOperation:
                    error = True
                    self.logger.error(f"montant '{row.row['montant']}' invalide pour operation ligne {index}")
                    continue
                date_releve = utils.strpdate(row.row["date"], "%d/%m/%Y")
                if "RETRAIT DAB" in row.detail:  # retrait espece
                    regex_retrait = re.compile(r"CARTE \S+ RETRAIT DAB(?: ETRANGER| SG)? (?P<date>\d\d/\d\d)")
                    retour = regex_retrait.match(row.detail)
                    if not retour:
                        self.logger.error(f"attention , probleme regex_retrait pour operation ligne {index}")
                        error = True
                        continue
                    cpt2 = self.account_cash
                    posting_1 = data.Posting(account=self.account_root, units=montant_releve, cost=None, flag=None, meta=None, price=None,)
                    posting_2 = data.Posting(
                        account=cpt2,
                        units=amount.Amount(montant_releve.number * decimal.Decimal("-1"), self.currency),
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    if self.account_cash:
                        if montant_releve.number < 0:
                            narration = "%s => %s" % (short(self.account_root), short(cpt2))
                        else:
                            narration = "%s => %s" % (short(cpt2), short(self.account_root))
                    transac = data.Transaction(
                        meta=meta,
                        date=date_releve,
                        flag=flag,
                        payee="Retrait",
                        narration=narration,
                        tags=data.EMPTY_SET,
                        links=data.EMPTY_SET,
                        postings=[posting_1, posting_2],
                    )
                    self.check_before_add(transac)
                    entries.append(transac)
                    continue
                # virement interne
                if "GENERATION VIE" in row.detail:
                    cpt2 = "Assets:Titre:Generation-vie:Cash"
                if "CPT 000304781" in row.detail:
                    cpt2 = "Assets:Titre:SG-LivretA"
                if "CPT 000341517" in row.detail:
                    cpt2 = "Assets:Titre:SG-LDD"
                if row.in_detail(r"PREL  VERST VOL", row.champ_detail) and row.in_detail(r"DE: SG", row.champ_detail):
                    cpt2 = "Assets:Titre:PEE:Cash"
                if cpt2:  # VIREMENT interne
                    posting_1 = data.Posting(account=self.account_root, units=montant_releve, cost=None, flag=None, meta=None, price=None,)
                    posting_2 = data.Posting(
                        account=cpt2,
                        units=amount.Amount(montant_releve.number * decimal.Decimal("-1"), self.currency),
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    tiers = "Virement"
                    if montant_releve.number < 0:
                        narration = "%s => %s" % (short(self.account_root), short(cpt2))
                    else:
                        narration = "%s => %s" % (short(cpt2), short(self.account_root))
                    links = data.EMPTY_SET
                    transac = data.Transaction(
                        meta=meta,
                        date=date_releve,
                        flag=flag,
                        payee=tiers.strip(),
                        narration=narration,
                        tags=data.EMPTY_SET,
                        links=links,
                        postings=[posting_1, posting_2],
                    )
                    entries.append(transac)
                    continue
                if row.in_detail(r"^CARTE \w\d\d\d\d(?! RETRAIT)"):  # cas general de la visa
                    reg_visa = r"(?:CARTE \w\d\d\d\d) (?:REMBT )?(?P<date>\d\d\/\d\d) (?P<desc>.*?)(?:\d+,\d\d|COMMERCE ELECTRONIQUE|$|\s\d+IOPD)"
                    retour = re.search(reg_visa, row.detail, re.UNICODE | re.IGNORECASE)
                    if retour:
                        tiers = self.tiers_update_verifie(retour.group("desc"))
                        if date_releve < utils.strpdate(f"{retour.group('date')}/{date_releve.year}", "%d/%m/%Y"):
                            date_visa = utils.strpdate(f"{retour.group('date')}/{date_releve.year - 1}", "%d/%m/%Y")
                        else:
                            date_visa = utils.strpdate(f"{retour.group('date')}/{date_releve.year}", "%d/%m/%Y")
                        if not tiers:
                            error = True
                            self.logger.error("attention , probleme regex visa pour operation ligne %s", index)
                            self.logger.error(f"{row.detail}")
                            continue
                    else:
                        error = True
                        self.logger.error("attention , probleme regex visa pour operation ligne %s", index)
                        self.logger.error(f"{row.detail}")
                        continue
                    posting_1 = data.Posting(account=self.account_root, units=montant_releve, cost=None, flag=None, meta=None, price=None,)
                    transac = data.Transaction(
                        meta=meta,
                        date=date_visa,
                        flag=flag,
                        payee=tiers,
                        narration="",
                        tags=data.EMPTY_SET,
                        links=data.EMPTY_SET,
                        postings=[posting_1, ],
                    )
                    self.check_before_add(transac)
                    entries.append(transac)
                else:
                    #  c'est un virement non transfert
                    regex_virement = r"VIR EUROPEEN EMIS \s* LOGITEL POUR: (.*?)(?: \d\d \d\d BQ \d+ CPT \S+)*? REF:"
                    if re.search(regex_virement, row.detail, re.UNICODE | re.IGNORECASE):
                        tiers = self.tiers_update_verifie(re.search(regex_virement, row.detail, re.UNICODE | re.IGNORECASE).group(1))
                    if "VIR EUROPEEN EMIS" in row.detail and not tiers:
                        error = True
                        self.logger.error(f"attention , probleme regex pour operation ligne {index}")
                        continue
                    # prelevement
                    if "PRELEVEMENT EUROPEEN" in row.detail or "PRLV EUROPEEN ACC" in row.detail:
                        tiers = self.tiers_update_verifie(f'{row.in_detail(r"DE:(.+?) ID:").strip()}')
                        if tiers == "None":
                            error = True
                            self.logger.error(f"attention , probleme regex pour operation ligne {index}")
                            continue
                    else:
                        if "VIR RECU" in row.detail and not tiers:
                            tiers = self.tiers_update_verifie(row.in_detail(r" DE: (.+?) (?:(?:MOTIF|REF):) "))
                    if row.in_detail("ECHEANCE PRET"):
                        tiers = "Sg"
                    if not tiers:
                        tiers = self.tiers_update_verifie(row.row["libelle"].capitalize())
                    transac = data.Transaction(
                        meta=meta,
                        date=date_releve,
                        flag=flags.FLAG_WARNING,
                        payee=tiers,
                        narration=narration,
                        tags=data.EMPTY_SET,
                        links=data.EMPTY_SET,
                        postings=[data.Posting(account=self.account_root, units=montant_releve, cost=None, flag=None, meta=None, price=None,)],
                    )
                    self.check_before_add(transac)
                    entries.append(transac)
        if error:
            raise Exception("au moins une erreur")
        return entries
