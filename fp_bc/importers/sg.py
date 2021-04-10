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
from beancount.parser import printer

from fp_bc.utils import CsvUnicodeReader
from fp_bc import utils


__version__ = "1.0.0"


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

    def extract(self, file: cache._FileMemo, existing_entries: t.Optional[bc_directives] = None) -> t.List[bc_directives]:
        # Open the CSV file and create directives.
        entries = []
        error = False
        with open(file.name, "r", encoding="windows-1252") as fichier:
            for index, row in enumerate(
                CsvUnicodeReader(fichier, champs=["date", "libelle", "detail", "montant", "devise"], ligne_saut=2, champ_detail="detail",), 4,
            ):
                tiers = None
                cpt2 = None
                narration = ""
                meta = data.new_metadata(file.name, index)
                if "CHEQUE" not in row.detail:
                    meta["comment"] = row.detail.strip()
                else:
                    narration = row.detail.strip()
                flag = None
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
                    if self.account_cash:
                        cpt2 = self.account_cash
                    else:
                        cpt2 = self.cat_default
                    posting_1 = data.Posting(account=self.account_root, units=montant_releve, cost=None, flag=None, meta=None, price=None,)
                    posting_2 = data.Posting(
                        account=cpt2,
                        units=amount.Amount(montant_releve.number * decimal.Decimal("-1"), self.currency),
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    tiers = "Retrait"
                    if self.account_cash:
                        if montant_releve.number < 0:
                            narration = "%s => %s" % (short(self.account_root), short(cpt2))
                        else:
                            narration = "%s => %s" % (short(cpt2), short(self.account_root))
                    transac = data.Transaction(
                        meta=meta,
                        date=date_releve,
                        flag=flags.FLAG_OKAY,
                        payee=tiers.strip(),
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
                # paiment ou credit carte bleu
                if "DEBIT MENSUEL CARTE" in row.detail or "CREDIT MENSUEL CARTE" in row.detail:
                    if self.account_visa:
                        cpt2 = self.account_visa
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
                        flag=flags.FLAG_OKAY,
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
                if row.in_detail(r"^CARTE \w\d\d\d\d(?! RETRAIT)"):  # cas general de la visa
                    flag = flags.FLAG_OKAY
                    reg_visa = r"(?:CARTE \w\d\d\d\d) (?:REMBT )?(?P<date>\d\d\/\d\d) (?P<desc>.*?)(?:\d+,\d\d|COMMERCE ELECTRONIQUE|$)"
                    retour = re.search(reg_visa, row.detail, re.UNICODE | re.IGNORECASE)
                    if retour:
                        tiers = retour.group("desc")
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
                    if self.account_visa:
                        posting_1 = data.Posting(account=self.account_visa, units=montant_releve, cost=None, flag=None, meta=None, price=None,)
                    else:
                        posting_1 = data.Posting(account=self.account_root, units=montant_releve, cost=None, flag=None, meta=None, price=None,)
                    tiers = self.tiers_update_verifie(tiers).strip()

                    cpt2 = self.cat(tiers)
                    posting_2 = data.Posting(
                        account=cpt2, units=amount.Amount(montant_releve.number * -1, self.currency), cost=None, flag=None, meta=None, price=None,
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
                    if not tiers:
                        #  c'est un virement non transfert
                        regex_virement = r"VIR EUROPEEN EMIS \s* LOGITEL POUR: (.*?)(?: \d\d \d\d BQ \d+ CPT \S+)*? REF:"
                        if re.search(regex_virement, row.detail, re.UNICODE | re.IGNORECASE):
                            tiers = re.search(regex_virement, row.detail, re.UNICODE | re.IGNORECASE).group(1)
                        if "VIR EUROPEEN EMIS" in row.detail and not tiers:
                            error = True
                            self.logger.error(f"attention , probleme regex pour operation ligne {index}")
                            continue
                        # prelevement
                        if "PRELEVEMENT EUROPEEN" in row.detail or "PRLV EUROPEEN ACC" in row.detail:
                            tiers = f'{row.in_detail(r"DE:(.+?) ID:").strip()}'
                            if tiers == "None":
                                error = True
                                self.logger.error(f"attention , probleme regex pour operation ligne {index}")
                                continue
                        else:
                            if "VIR RECU" in row.detail and not tiers:
                                tiers = row.in_detail(r" DE: (.+?) (?:(?:MOTIF|REF):) ")
                        if row.in_detail("ECHEANCE PRET"):
                            tiers = "Sg"
                        if tiers:
                            tiers = self.tiers_update_verifie(tiers)
                        else:
                            tiers = self.tiers_update_verifie(row.detail)
                        if not tiers:
                            tiers = "Inconnu"
                    cpt2 = self.cat(tiers)
                    #  on gere le cas special de la sg
                    if row.in_detail("ECHEANCE PRET"):
                        cpt2 = "Expenses:Lgmt:Pret"
                    if not cpt2:
                        cpt2 = self.cat_default
                    posting_1 = data.Posting(account=self.account_root, units=montant_releve, cost=None, flag=None, meta=None, price=None,)
                    posting_2 = data.Posting(
                        account=cpt2, units=amount.Amount(montant_releve.number * -1, self.currency), cost=None, flag=None, meta=None, price=None,
                    )
                    transac = data.Transaction(
                        meta=meta,
                        date=date_releve,
                        flag=flags.FLAG_OKAY,
                        payee=tiers.strip(),
                        narration=narration,
                        tags=data.EMPTY_SET,
                        links=data.EMPTY_SET,
                        postings=[posting_1, posting_2],
                    )
                    self.check_before_add(transac)
                    entries.append(transac)
            if error:
                raise Exception("au moins une erreur")
            fichier.seek(0)
            row = fichier.readline().split(";")
            meta = data.new_metadata(file.name, index)
            entry = data.Balance(
                account=self.account_root,
                amount=amount.Amount(utils.to_decimal(row[5][:-5]), self.currency),
                meta=meta,
                date=utils.strpdate(row[4], "%d/%m/%Y") + datetime.timedelta(days=1),
                tolerance=None,
                diff_amount=None,
            )
            try:
                data.sanity_check_types(entry)
                entries.append(entry)
            except AssertionError as exp:
                self.logger.error(f"error , problem assertion {pprint.pformat(exp)} in the balance {pprint.pformat(entry)}")
        return entries


class ImporterSG_Visa(importer.ImporterProtocol):
    def __init__(
        self,
        tiers_update: t.Sequence[t.Sequence[str]],
        tiers_cat: t.Sequence[t.Sequence[str]],
        currency: str,
        cat_default: str,
        account_id: str,
        account_root: str,
    ) -> None:
        self.tiers_update = tiers_update
        self.tiers_cat = tiers_cat
        self.logger = logging.getLogger(__file__)  # pylint: disable=W0612
        self.currency = currency
        self.account_root = account_root
        self.cat_default = cat_default
        self.account_id = account_id

    def identify(self, file: t.IO) -> t.Optional[t.Match[str]]:
        return re.match(f"{self.account_id}.*.csv", path.basename(file.name))

    def file_account(self, _: t.IO) -> str:
        return self.account_root

    def extract(self, file: cache._FileMemo, existing_entries: t.Optional[bc_directives] = None) -> t.List[bc_directives]:
        # Open the CSV file and create directives.
        entries = []
        error = False
        with open(file.name, "r", encoding="windows-1252") as fichier:
            for index, row in enumerate(
                CsvUnicodeReader(fichier, champs=["date", "date_visa", "detail", "montant", "devise"], ligne_saut=2, champ_detail="detail",), 4,
            ):
                tiers = None
                meta = data.new_metadata(file.name, index)
                meta["comment"] = row.detail.strip()
                flag = flags.FLAG_OKAY
                try:
                    montant_releve = amount.Amount(utils.to_decimal(row.row["montant"]), self.currency)
                except decimal.InvalidOperation:
                    error = True
                    self.logger.error(f"montant '{row.row['montant']}' invalide pour operation ligne {index}")
                    continue
                date = utils.strpdate(row.row["date"], "%d/%m/%Y")
                reg_visa = r"\d\d\d\d\/(?P<desc>.*) \d"
                retour = re.search(reg_visa, row.detail, re.UNICODE | re.IGNORECASE)
                if retour:
                    tiers = retour.group("desc")
                    for regle_tiers in self.tiers_update:
                        try:
                            if re.search(regle_tiers[0], tiers, re.UNICODE | re.IGNORECASE):
                                tiers = regle_tiers[1]
                            else:
                                tiers = tiers.capitalize()
                        except TypeError:
                            error = True
                            self.logger.error(f"regle:{regle_tiers[0]} - tiers: {tiers}")
                            self.logger.error("attention , probleme regex visa pour operation ligne %s", index)
                            self.logger.error(f"{row.detail}")
                            raise Exception("erreur")
                    if not tiers:
                        error = True
                        self.logger.error("attention , probleme regex visa pour operation ligne %s", index)
                        self.logger.error(f"{row.detail}")
                        raise Exception("erreur")
                else:
                    error = True
                    self.logger.error("attention , probleme regex visa pour operation ligne %s", index)
                    self.logger.error(f"{row.detail}")
                    raise Exception("erreur")

                cat = None
                for regle_cat in self.tiers_cat:
                    if re.search(regle_cat[0], tiers, re.UNICODE | re.IGNORECASE):
                        cat = regle_cat[1]
                if not cat:
                    cat = self.cat_default
                posting_1 = data.Posting(account=self.account_root, units=montant_releve, cost=None, flag=None, meta=None, price=None)
                posting_2 = data.Posting(
                    account=cat, units=amount.Amount(montant_releve.number * -1, self.currency), cost=None, flag=None, meta=None, price=None,
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
                try:
                    data.sanity_check_types(transac)
                    for posting in transac.postings:
                        if posting.account is None:
                            raise AssertionError(f"error , problem assertion {pprint.pformat(posting)} in the transaction {pprint.pformat(transac)}")
                    if len(transac.postings) < 2:
                        raise AssertionError(f"error , problem assertion {pprint.pformat(posting)} in the transaction {pprint.pformat(transac)}")
                except AssertionError as exc:
                    try:
                        print(exc)
                        printer.print_entry(transac)
                    except TypeError:
                        pprint.pprint(transac)
                        # error = True
                        break
                entries.append(transac)
        if error:
            raise Exception("au moins une erreur")
        return entries
