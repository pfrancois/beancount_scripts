there is in this folder two importers.
one for csv from societe generale: ImporterSG
one for csv from postbank: ImporterPB
also a price source:
the price should be like :

price: "EUR:fp_importer_beancount.import_cours_amf/FR0000431538"

be aware that you need some config in order that it works for the importer .

# quick start

```python
from fp_importer_beancount.import_sg import ImporterSG
from fp_importer_beancount.import_pb import ImporterPB
tiers_update = (('BURGER KING', 'Burger King'),
                  (r'AUCHAN .*', 'Auchan'))
tiers_cat = (('Auchan', 'Expenses:Alimentation:Supermarche'),
            ('Burger King', 'Expenses:Alimentation:Restaurant'),)
  CONFIG = [
      ImporterSG(tiers_update=tiers_update,
                  tiers_cat=tiers_cat,
                  currency = "EUR",
                  account_root = "Assets:Banque:SG",
                  account_cash = "Assets:Caisse",
                  cat_default =  'Expenses:Non-affecte',
                  cat_frais = "Expenses:Frais-bancaires",
                  account_visa="Assets:Banque:SG-Visa"),
      ImporterPB(tiers_update=tiers_update,
                  tiers_cat=tiers_cat,
                  currency = "EUR",
                  account_root = "Assets:Banque:SG",
                  account_cash = "Assets:Caisse",
                  cat_default =  'Expenses:Non-affecte',
                  cat_frais = "Expenses:Frais-bancaires")
  ]
```

ou can see in the config, you neeed to define :
# for ImporterSG and ImporterPB
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
  name of the account that will be used when no account is find previously
 - cat_frais
 name of the account that will be used when card fees are found
 # for ImporterSG
 - account_visa
name of the account the will used for any visa card related.
if found a date of operation that differ from the date accounted: it will create metadata ```date_visa```
it will create one transaction at he date accounted that 'tranfer' in order to pay the spending of the month
it will create a balance operation at the end
