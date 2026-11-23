name: Deploy Leaguezz

on:
  workflow_dispatch:  # Manual button in GitHub app - Actions > Deploy Leaguezz > Run workflow

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install py-algorand-sdk
      - name: Deploy contract to Testnet
        env:
          DEPLOYER_MNEMONIC: ${{ secrets.DEPLOYER_MNEMONIC }}
        run: python deploy.py
