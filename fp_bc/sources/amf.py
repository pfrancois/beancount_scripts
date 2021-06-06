# -*- coding: utf-8 -*-
""" source pour les sicav amf """

import datetime
import time
import logging
import pytz
from beancount.prices import source as bean_source
import bs4  # type: ignore

import requests
from fp_bc import utils


class AmfException(utils.UtilsException):
    """juste une exception qui gere le format"""

    pass


class Source(bean_source.Source):
    def get_latest_price(self, ticker):
        log = logging.getLogger()
        log.info(f"AMF:{ticker}")
        time.sleep(5)
        payload = {
            "varvalidform": "on",
            "NomProd": "",
            "FAMILLEPROD": "0",
            "selectNRJ": "0",
            "NumAgr": "",
            "CLASSPROD": "0",
            "CodeISIN": ticker,
            "NomSOc": "",
            "action": "new",
            "valid_form": "Lancer+la+recherche",
            "sltix": "1+2+3+INVESTMENT+MANAGERS",
        }
        req = requests.get("https://geco.amf-france.org/Bio/rech_part.aspx", params=payload)
        soup = bs4.BeautifulSoup(req.content, "html.parser")
        if soup.find("label", {"id": "Nbrep"}) and soup.find("label", {"id": "Nbrep"}).find("caption").string == "Votre recherche a abouti à 0 réponse(s).":
            log.error("pas de correspondance pour le ticker %s dans la base de l'AMF" % ticker)
        else:
            values = soup.find_all(class_="ResultatCritereValue")
            keys = soup.find_all(class_="ResultatCritere")
            result = dict(zip([v.get_text() for v in keys], [v.get_text() for v in values]))
            try:
                date_req = utils.strpdate(result["Date VL :"], fmt="%d/%m/%Y")
                dt = datetime.datetime(date_req.year, date_req.month, date_req.day, tzinfo=pytz.utc)
                if result["Valeur (€) :"][-2:] == "00" and result["Valeur (€) :"].find(",") != -1 and len(result["Valeur (€) :"]) > 4:
                    result["Valeur (€) :"] = result["Valeur (€) :"][:-2]
                montant_req = utils.to_decimal(s=result["Valeur (€) :"], virgule=True, space=True)
                return bean_source.SourcePrice(montant_req, dt, "EUR")
            except Exception:
                log.error("erreur pour le ticker %s" % ticker)
