# here ou will find three importers for [beancount](https://github.com/beancount/beancount)
## two for csv from societe generale
 ImporterSG and ImporterSG_Visa as SG made two type of csv files. one for "normal account" , one for visa with deffered debit.
## one for csv from postbank: ImporterPB
# a price source in the folder source
# a plugin price who transform in price all the cost.

# for the price importer
the price should be like :
```
price: "EUR:fp_importer_beancount.import_cours_amf/FR0000431538"
```
be aware that you need some config in order that it works for the importer .

# quick start for the importers

```python
from fp_bc.importers import sg

tiers_update = (('BURGER KING', 'Burger King'),
                  (r'AUCHAN .*', 'Auchan'))
tiers_cat = (('Auchan', 'Expenses:Alimentation:Supermarche'),
            ('Burger King', 'Expenses:Alimentation:Restaurant'),)
CONFIG = [
    sg.ImporterSG(
        tiers_update=tiers_update,
        tiers_cat=tiers_cat,
        currency=currency,
        account_root="Assets:Banque:SG",
        account_id="0123456789",
        account_cash="Assets:Caisse",
        cat_default="Expenses:Non-affecte",
        account_visa="Assets:Banque:SG-Visa",
    ),
    sg.ImporterSG_Visa(
        tiers_update=tiers_update,
        tiers_cat=tiers_cat,
        currency="EUR",
        account_root="Assets:Banque:SG-Visa",
        account_id="987654321",
        cat_default="Expenses:Non-affecte",
    ),
]
```

ou can see in the config, you neeed to define :
# for ImporterSG and ImporterPB and ImporterSG_Visa
 - tiers_update
  it is to be able to harmonize the name of the payee
 list with for each element:
	 - regular expression (it could be normal text) that take the initial name of the payee
	 - text to have the final name of the payee
  we could have different initial name that give to the same final name.
  for example:

-
 example:
```python
 tiers_update = (('BURGER KING', 'Burger King'),
                  ('burger king', 'Burger King'),
                  ('BK253', 'Burger King'),
                  (r'AUCHAN .*', 'Auchan'))
```

 - tiers_cat
  it is to be able to map the name of the payee and the account
  two string:
  (payee_name, account_name)
 example:
 ```python
 tiers_cat = (('Auchan', 'Expenses:Alimentation:Supermarche'),
            ('Casino', 'Expenses:Alimentation:Supermarche'),)
   ```
 - currency
  name of the currency used to import

 - account_root
  name of the main account

 - account_cash
  name of the account that is used when you withdraw cash from a banking account

 - cat_default
  name of the account that will be used when no account is find previously with tiers_cat
 - cat_frais
 name of the account that will be used when card fees are found
 # for ImporterSG and ImporterSG_Visa
 - account_visa
name of the account the will used for any visa card related.
 - account_id
    id of the account, it will be also the id of the file. currently , it is the easiest way to differentiate the normal accout file and the visa csv file.
