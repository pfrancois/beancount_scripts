# coding=utf-8
import logging
import re
from os import path
import pprint
import decimal
import typing as t
import datetime

from beancount.core import amount
from beancount.core import account
from beancount.core import data  # pylint:disable=E0611
from beancount.core import flags
from beancount.ingest import importer  # noqa

from fp_bc.utils import CsvUnicodeReader
from fp_bc import utils


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
        account_cash: str,
        cat_default: str,
        cat_frais: str,
        account_visa: str,
    ) -> None:
        self.tiers_update = tiers_update
        self.tiers_cat = tiers_cat
        self.logger = logging.getLogger(__file__)  # pylint: disable=W0612
        self.currency = currency
        self.account_root = account_root
        self.account_cash = account_cash
        self.cat_default = cat_default
        self.cat_frais = cat_frais
        self.account_visa = account_visa

    def identify(self, file: t.IO) -> t.Optional[t.Match[str]]:
        return re.match(r"Export_\d*_\d*_\d*.csv", path.basename(file.name))

    def file_account(self, _: t.IO) -> str:
        return self.account_root

    def check_before_add(self, entry: data.Transaction) -> None:
        try:
            data.sanity_check_types(entry)
            for posting in entry.postings:
                if posting.account is None:
                    raise AssertionError("problem")
        except AssertionError as exp:
            self.logger.error(
                "error , problem assertion %s in the transaction %s", pprint.pformat(exp), pprint.pformat(entry),
            )

    def cat(self, tiers: str) -> str:
        for regle_cat in self.tiers_cat:
            if re.search(regle_cat[0], tiers, re.UNICODE | re.IGNORECASE):
                return regle_cat[1]
        return self.cat_default

    def tiers_update_verifie(self, tiers: str) -> str:
        for regle_tiers in self.tiers_update:
            if re.search(regle_tiers[0], tiers, re.UNICODE | re.IGNORECASE):
                tiers = regle_tiers[1]
        return tiers

    def extract(self, file: t.IO, existing_entries: t.Optional[bc_directives] = None) -> t.List[bc_directives]:
        # Open the CSV file and create directives.
        entries = []
        paiment_carte_visa: t.Dict[str, t.Optional[decimal.Decimal]] = {}
        error = False
        with open(file.name, "r", encoding="windows-1252") as fichier:
            for index, row in enumerate(
                CsvUnicodeReader(
                    fichier, champs=["date", "detail", "montant", "devise"], ligne_saut=2, champ_detail="detail",
                ),
                4,
            ):
                tiers = None
                cpt2 = None
                narration = ""
                meta = data.new_metadata(file.name, index)
                meta["comment"] = row.detail.strip()
                meta['update_time'] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                flag = None
                try:
                    montant_releve = amount.Amount(utils.to_decimal(row.row["montant"]), self.currency)
                except decimal.InvalidOperation:
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
                    posting_1 = data.Posting(
                        account=self.account_root, units=montant_releve, cost=None, flag=None, meta=None, price=None,
                    )
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
                if cpt2:  # VIREMENT interne
                    posting_1 = data.Posting(
                        account=self.account_root, units=montant_releve, cost=None, flag=None, meta=None, price=None,
                    )
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
                # paiment carte visa
                if row.in_detail(r"^CARTE \w\d\d\d\d(?! RETRAIT)"):  # cas general de la visa
                    meta["date_visa"] = str(date_releve)
                    flag = flags.FLAG_OKAY
                    if date_releve.month == 1:  # si on est en janvier , les depenses sont celles de decembre
                        annee = date_releve.year - 1
                    else:
                        annee = date_releve.year
                    reg_visa = r"(?:CARTE \w\d\d\d\d) (?:REMBT )?(?P<date>\d\d\/\d\d) (?P<desc>.*?)(?:\d+,\d\d|COMMERCE ELECTRONIQUE|$)"
                    retour = re.search(reg_visa, row.detail, re.UNICODE | re.IGNORECASE)
                    if retour:
                        tiers = retour.group("desc")
                        if not tiers:
                            error = True
                            self.logger.error("attention , probleme regex visa pour operation ligne %s", index)
                            self.logger.error(f"{row.detail}")
                            continue
                        date = utils.strpdate("%s/%s" % (retour.group("date"), annee), "%d/%m/%Y")
                    else:
                        error = True
                        self.logger.error("attention , probleme regex visa pour operation ligne %s", index)
                        self.logger.error(f"{row.detail}")
                        continue
                    paiment_carte_visa[meta["date_visa"]] = (
                        paiment_carte_visa.get(meta["date_visa"], decimal.Decimal("0")) + montant_releve.number
                    )
                    posting_1 = data.Posting(
                        account=self.account_visa, units=montant_releve, cost=None, flag=None, meta=None, price=None,
                    )
                    tiers = self.tiers_update_verifie(tiers).strip()

                    if not tiers:
                        tiers = "Inconnu"
                    cpt2 = self.cat(tiers)

                    posting_2 = data.Posting(
                        account=cpt2,
                        units=amount.Amount(montant_releve.number * -1, self.currency),
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
                    continue
                else:
                    if not tiers:
                        #  c'est un virement non transfert
                        regex_virement = r"VIR EUROPEEN EMIS   LOGITEL POUR: (.*?)(?: \d\d \d\d BQ \d+ CPT \d+)*? REF:"
                        if re.search(regex_virement, row.detail, re.UNICODE | re.IGNORECASE):
                            tiers = re.search(regex_virement, row.detail, re.UNICODE | re.IGNORECASE).group(1)
                        if "VIR EUROPEEN EMIS" in row.detail and not tiers:
                            error = True
                            self.logger.error("attention , probleme regex pour operation ligne %s", index)
                            continue
                        # prelevement
                        if "PRELEVEMENT EUROPEEN" in row.detail:
                            tiers = f'{row.in_detail(r" DE: (.+?) ID:")} - {row.in_detail(r"MOTIF: (.+)")}'
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
                    posting_1 = data.Posting(
                        account=self.account_root, units=montant_releve, cost=None, flag=None, meta=None, price=None,
                    )
                    posting_2 = data.Posting(
                        account=cpt2,
                        units=amount.Amount(montant_releve.number * -1, self.currency),
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    flag = flags.FLAG_OKAY
                    transac = data.Transaction(
                        meta=meta,
                        date=date_releve,
                        flag=flag,
                        payee=tiers.strip(),
                        narration=narration,
                        tags=data.EMPTY_SET,
                        links=data.EMPTY_SET,
                        postings=[posting_1, posting_2],
                    )
                    self.check_before_add(transac)
                    entries.append(transac)
        if paiment_carte_visa:
            i = 0
            for date_paiment_visa in paiment_carte_visa:
                i = i + 1
                tiers = None
                cpt2 = None
                meta = data.new_metadata("created on the spot", i)
                montant = paiment_carte_visa[date_paiment_visa]
                unit = amount.Amount(utils.to_decimal(montant) * -1, self.currency)
                unit_opp = amount.Amount(utils.to_decimal(montant), self.currency)
                posting_1 = data.Posting(
                    account=self.account_visa, units=unit, cost=None, flag=None, meta=None, price=None,
                )
                posting_2 = data.Posting(
                    account=self.account_root, units=unit_opp, cost=None, flag=None, meta=None, price=None,
                )
                tiers = "Virement"
                meta["date_visa"] = date_paiment_visa
                transac = data.Transaction(
                    meta=meta,
                    date=utils.strpdate(date_paiment_visa),
                    flag=flags.FLAG_OKAY,
                    payee=tiers.strip(),
                    narration=f"{short(self.account_root)} => {short(self.account_visa)}",
                    tags=data.EMPTY_SET,
                    links=data.EMPTY_SET,
                    postings=[posting_1, posting_2],
                )
                self.check_before_add(transac)
                entries.append(transac)
        if error:
            raise Exception("au moins une erreur")
        return entries
