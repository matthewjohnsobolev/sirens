# Package marker: tests/unit/alerts and tests/unit/bi both hold a test_main.py
# and a test_cli.py. Without these markers pytest names modules by basename
# alone and the second file of each pair fails to collect.
