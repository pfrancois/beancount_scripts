from distutils.core import setup

setup(
    name="fp_beancount",
    version="2.0.0",
    author="Francois pegory",
    author_email="pfrancois_99@yahoo.fr",
    packages=setuptools.find_packages(),
    keywords=['beancount', 'convert', 'converter', 'csv', 'accounting'],
    url="https://github.com/pfrancois/beancount_scripts",
    license="Creative Commons Attribution-Noncommercial-Share Alike license",
    description="prices sources , plugins and importer for beancount",
    install_requires=["beancount", "pytz", "requests", "bs4"],
    classifiers=[
        'Programming Language :: Python :: 3 :: Only',
        'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
        "Operating System :: OS Independent",
        'Topic :: Office/Business :: Financial :: Accounting',
         'Natural Language :: French',
         'Development Status :: 5 - Production/Stable'
    ]
)
