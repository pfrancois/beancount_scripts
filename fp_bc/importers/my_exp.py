import json

# coding=utf-8
import logging

# import re
# from os import path
import os
import pprint
import decimal
import typing as t
import unicodedata
import re

# import datetime  # noqa

from beancount.core import amount

# from beancount.core import account
from beancount.core import data  # pylint:disable=E0611
from beancount.core import flags
from beancount.ingest import importer
from beancount.ingest import cache

from fp_bc import utils
from fp_bc import utils_bc


def mapping_cat(cat_json_to_map: t.Union[str, t.List], list_categories: t.List[str]) -> str:
    # capitalise
    if not isinstance(cat_json_to_map, (str)):
        cat_json_to_map = [c.capitalize() for c in cat_json_to_map]
        temp = ":".join(cat_json_to_map)
    else:
        temp = cat_json_to_map.capitalize()
    # remove accents
    temp = ''.join(c for c in unicodedata.normalize('NFD', temp) if unicodedata.category(c) != 'Mn')
    # efface espaces
    temp = temp.strip()
    if temp == "Ost":
        return "Expenses:OST"
    else:
        for c in list_categories:
            if temp in c:
                return c
    raise Exception(f"{temp} inconnu")


class Importer_myexp(importer.ImporterProtocol):
    def __init__(self, mapping_comptes: t.Dict[str, str]) -> None:
        self.mapping = mapping_comptes

    def name(self) -> str:
        # permet d'avoir deux comptes et de pouvoir les differenciers au niveau de la config
        return f"{self.__class__.__name__}"

    def identify(self, file: cache._FileMemo) -> bool:
        # defini comment on trouve le fichier
        return bool(re.match(".*.json", os.path.basename(file.name)))

    def file_account(self, _: cache._FileMemo) -> str:
        # defini le nom du repertoire de sauvegarde
        return "generique"

    def extract(self, file: cache._FileMemo, existing_entries: t.Optional[t.List[utils_bc.bc_directives]] = None) -> t.List[utils_bc.bc_directives]:
        list_categories: t.List[str] = list()
        list_comptes: t.List[str] = list()
        uuid_existant: t.List[str] = list()
        if existing_entries is not None:
            for entry in existing_entries:
                if isinstance(entry, data.Open):
                    if "Assets" in entry.account:
                        list_comptes.append(entry.account)
                    else:
                        list_categories.append(entry.account)
                if isinstance(entry, data.Transaction):
                    if "uuid" in entry.meta:
                        uuid_existant.append(entry.meta["uuid"])
                    for p in entry.postings:
                        if p.meta is not None and "uuid" in p.meta:
                            uuid_existant.append(p.meta["uuid"])
        logger = logging.getLogger(__file__)
        entries: t.List[utils_bc.bc_directives] = list()
        error = False
        with open(file.name, encoding='UTF-8') as f:
            data_json = json.load(f)
        # a depkacer
        mapping_compte = self.mapping
        for index_compte, compte_json in enumerate(data_json):
            compte_name = mapping_compte[compte_json["label"]]
            currency = compte_json["currency"]
            for index, t_json in enumerate(compte_json["transactions"]):
                if t_json["uuid"] in uuid_existant:
                    logger.warning(f'{t_json["uuid"]} déja existant')
                    continue
                meta = data.new_metadata(file.name, index)
                meta["uuid"] = t_json["uuid"]
                flag = None
                tiers = None
                cpt2 = None
                narration = ""
                links = data.EMPTY_SET
                tags = data.EMPTY_SET
                date_releve = utils.strpdate(t_json["date"])
                try:
                    montant_releve = amount.Amount(utils.to_decimal(t_json["amount"]), currency)
                except decimal.InvalidOperation:
                    error = True
                    logger.error(f"montant '{t_json['amount']}' invalide pour uuid  {t_json['uuid']}")
                    continue
                if montant_releve.number is None:
                    number = decimal.Decimal("0")
                else:
                    number = montant_releve.number
                if "transferAccount" in t_json:  # virement
                    cpt2 = mapping_compte[t_json["transferAccount"]]
                    tiers = "Virement"
                    if number > 0:
                        continue  # on evite le double comptage du virement
                    else:
                        narration = "%s => %s" % (utils_bc.short(compte_name), utils_bc.short(cpt2))

                    posting_1 = data.Posting(
                        account=compte_name,
                        units=montant_releve,
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    posting_2 = data.Posting(
                        account=cpt2,
                        units=amount.Amount(number * decimal.Decimal("-1"), currency),
                        cost=None,
                        flag=None,
                        meta=None,
                        price=None,
                    )
                    if 'tags' in t_json:
                        tags = set(t_json['tags'])
                    transac = data.Transaction(
                        meta=meta,
                        date=date_releve,
                        flag=flags.FLAG_OKAY,
                        payee=tiers.strip(),
                        narration=narration,
                        tags=tags,
                        links=links,
                        postings=[posting_1, posting_2],
                    )
                    utils_bc.check_before_add(transac)
                    entries.append(transac)
                    uuid_existant.append(t_json["uuid"])
                    continue
                else:
                    if "splits" not in t_json:
                        if "payee" not in t_json:
                            tiers = "inconnu"
                        else:
                            tiers = t_json["payee"]
                            if tiers is None:
                                tiers = "inconnu"
                        if "category" not in t_json:
                            category = mapping_cat('inconnu', list_categories)
                            continue
                        else:
                            category = mapping_cat(t_json["category"], list_categories)
                        posting_1 = data.Posting(
                            account=compte_name,
                            units=montant_releve,
                            cost=None,
                            flag=None,
                            meta=None,
                            price=None,
                        )
                        posting_2 = data.Posting(
                            account=category,
                            units=amount.Amount(number * decimal.Decimal("-1"), currency),
                            cost=None,
                            flag=None,
                            meta=None,
                            price=None,
                        )
                        if 'tags' in t_json:
                            tags = set(t_json['tags'])
                        if 'comment' in t_json:
                            narration = t_json['comment']
                        transac = data.Transaction(
                            meta=meta,
                            date=date_releve,
                            flag=flags.FLAG_OKAY,
                            payee=tiers.strip(),
                            narration=narration,
                            tags=tags,
                            links=links,
                            postings=[posting_1, posting_2],
                        )
                        utils_bc.check_before_add(transac)
                        entries.append(transac)
                        uuid_existant.append(t_json["uuid"])
                        continue
                    else:
                        if "payee" not in t_json:
                            tiers = "inconnu"
                        else:
                            tiers = t_json["payee"]
                            if tiers is None:
                                tiers = "inconnu"
                        posting_main = data.Posting(
                            account=compte_name,
                            units=montant_releve,
                            cost=None,
                            flag=None,
                            meta=None,
                            price=None,
                        )
                        liste_posting = [
                            posting_main,
                        ]
                        narration_l = list()
                        narration = ""
                        for p_json in t_json['splits']:
                            try:
                                montant_releve_s = amount.Amount(utils.to_decimal(p_json["amount"]), currency)
                            except decimal.InvalidOperation:
                                error = True
                                logger.error(f"montant '{p_json['amount']}' invalide pour uuid  {p_json['uuid']}")
                                continue
                            except TypeError:
                                logger.error(f"erreur: {p_json}")
                            if montant_releve_s.number is None:
                                number_s = decimal.Decimal("0")
                            else:
                                number_s = montant_releve_s.number
                            meta_p: t.Optional[data.Meta] = None
                            if "transferAccount" in p_json:  # virement
                                category = mapping_compte[p_json["transferAccount"]]
                                meta_p = {'uuid': p_json["uuid"]}
                                if number < 0 and tiers == "inconnu":
                                    tiers = "virement"
                                    narration = "%s => %s" % (utils_bc.short(compte_name), utils_bc.short(category))
                            else:
                                meta_p = None
                                if 'comment' in p_json:
                                    narration_l.append(p_json['comment'])
                                try:
                                    category = mapping_cat(p_json["category"], list_categories)
                                except KeyError:
                                    category = mapping_cat("inconnu", list_categories)
                            if not narration:
                                narration = "/".join(narration_l)
                            posting_c = data.Posting(
                                account=category,
                                units=amount.Amount(number_s * decimal.Decimal("-1"), currency),
                                cost=None,
                                flag=None,
                                meta=meta_p,
                                price=None,
                            )
                            liste_posting.append(posting_c)
                            uuid_existant.append(p_json["uuid"])
                        if 'tags' in t_json:
                            tags = set(t_json['tags'])
                        transac = data.Transaction(
                            meta=meta,
                            date=date_releve,
                            flag=flags.FLAG_OKAY,
                            payee=tiers.strip(),
                            narration=narration,
                            tags=tags,
                            links=links,
                            postings=liste_posting,
                        )
                        utils_bc.check_before_add(transac)
                        entries.append(transac)
                        uuid_existant.append(t_json["uuid"])
                        continue
        return entries
