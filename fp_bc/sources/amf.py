# -*- coding: utf-8 -*-
""" source pour les sicav amf """

import datetime
import time
import logging
import pytz
from dateutil.parser import parse as parse_datetime
from beancount.prices import source as bean_source
from beancount.core.number import D
import bs4
import typing
import datetime

import requests
from fp_bc import utils


class AmfException(utils.UtilsException):
    """juste une exception qui gere le format"""

    pass


class Source(bean_source.Source):
    def get_latest_price(self, ticker: str) -> typing.Optional[bean_source.SourcePrice]:
        try:
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
            if (
                soup.find("label", {"id": "Nbrep"})
                and soup.find("label", {"id": "Nbrep"}).find("caption").string == "Votre recherche a abouti à 0 réponse(s)."
            ):
                raise AmfException("pas de correspondance pour le ticker %s dans la base de l'AMF" % ticker)
            else:
                values = soup.find_all(class_="ResultatCritereValue")
                keys = soup.find_all(class_="ResultatCritere")
                result = dict(zip([v.get_text() for v in keys], [v.get_text() for v in values]))
                try:
                    date_req = utils.strpdate(result["Date VL :"], fmt="%d/%m/%Y")
                    timezone = pytz.timezone('Europe/Paris')
                    dt = timezone.localize(datetime.datetime(date_req.year, date_req.month, date_req.day, 17, 30))

                    thePrice = soup.find("td", text="Valeur (€) :").next_sibling.get_text(strip=True)
                    montant_req = D(thePrice.replace(" ", "").replace(",", ".")).quantize(D("0.01"))
                    return bean_source.SourcePrice(montant_req, dt, "EUR")
                except Exception:
                    raise AmfException("erreur pour le ticker %s" % ticker)
        except AmfException as e:
            log.error(str(e))
            return None

    def get_historical_price(self, ticker: str, time: datetime.datetime) -> typing.Optional[bean_source.SourcePrice]:
        """Return the historical price found for the symbol at the given date.
        This could be the price of the close of the day, for instance. We assume
        that there is some single price representative of the day.
        Args:
          ticker: A string, the ticker to be fetched by the source. This ticker
            may include structure, such as the exchange code. Also note that
            this ticker is source-specified, and is not necessarily the same
            value as the commodity symbol used in the Beancount file.
          time: The timestamp at which to query for the price. This is a
            timezone-aware timestamp you can convert to any timezone. For past
            dates we query for a time that is equivalent to 4pm in the user's
            timezone.
        Returns:
          A SourcePrice instance. If the price could not be fetched, None is
          returned and another source should be consulted. There is never any
          guarantee that a price source will be able to fetch its value; client
          code must be able to handle this. Also note that the price's returned
          time must be timezone-aware.
        """
        log = logging.getLogger()
        log.info(f"AMF:{ticker}")
        s = requests.Session()
        url = (
            "https://geco.amf-france.org"
            + "/Bio/rech_part.aspx?varvalidform=on&CodeISIN="
            + ticker
            + "&CLASSPROD=0&NumAgr=&selectNRJ=0&NomProd=&NomSOc=&action=new&valid_form=Lancer+la+recherche"
        )

        r = s.get(url)
        soup = bs4.BeautifulSoup(r.text, "html.parser")
        try:
            numProd = soup.find("input", {"name": "NumProd"})["value"]
            numPart = soup.find("input", {"name": "NumPart"})["value"]
        except Exception:
            log.error("ISIN introuvable sur AMFGeco")
            return None

        url = (
            "https://geco.amf-france.org"
            + "Bio/info_part.aspx?SEC=VL&NumProd=" + numProd
            + "&NumPart=" + numPart
            + "&DateDeb=" + str(time.date().day) + "%2F" + str(time.date().month) + "%2F" + str(time.date().year)
            + "&DateFin=" + str(time.date().day) + "%2F" + str(time.date().month) + "%2F" + str(time.date().year)
            + "&btnvalid=OK"
        )

        r = s.get(url)
        soup = bs4.BeautifulSoup(r.text, "html.parser")
        try:
            theDate = soup.find("tr", class_="ligne2").find_all("td")[0].get_text(strip=True)
            theDate = parse_datetime(theDate, dayfirst=True)
            fr_timezone = pytz.timezone("Europe/Paris")
            theDate = theDate.astimezone(fr_timezone)

            thePrice = soup.find("tr", class_="ligne2").find_all("td")[1].get_text(strip=True)
            thePrice = D(thePrice.replace(" ", "").replace(",", ".")).quantize(D("0.01"))
            return bean_source.SourcePrice(thePrice, theDate, "EUR")
        except Exception:
            log.error("Pas de valeur liquidative publiée à cette date sur AMFGeco")
            return None
