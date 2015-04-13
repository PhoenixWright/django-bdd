from setuptools import setup, find_packages

args = dict(
    name='Django-bdd',
    version='1.0',
    # declare your packages
    packages=find_packages(exclude=("test",)),
    include_package_data=True,  # declarations in MANIFEST.in
)

setup(**args)
