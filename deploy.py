import os
import base64
from algosdk import account, mnemonic, transaction
from algosdk.v2client import algod

ALGOD = "https://testnet-api.algonode.cloud"

# Your existing App - from last log
APP_ID = 777121961
APP_ADDRESS = "WY44FPW42JOEZJSVO2BN5VXQOG5KIWQ4TG5C2BYKXWHBD4HYPSVTMGXT5E"

def main():
    seed = os.environ.get("DEPLOYER_MNEMONIC", "").strip()
    if not seed:
        raise SystemExit("ERROR: DEPLOYER_MNEMONIC secret is empty.")
    if len(seed.split()) == 25:
        sk = mnemonic.to_private_key(seed)
        addr = account.address_from_private_key(sk)
    else:
        sk = base64.b64decode(seed)
        addr = account.address_from_private_key(sk)
    print(f"Deployer: {addr}")
    print(f"Using existing App: {APP_ID}")
    print(f"App Address: {APP_ADDRESS}")
    client = algod.AlgodClient("", ALGOD)

    print("Funding app 1 ALGO...")
    params = client.suggested_params()
    fund = transaction.PaymentTxn(addr, params, APP_ADDRESS, 1_000_000)
    txid = client.send_transaction(fund.sign(sk))
    print(f"Fund Tx: {txid}")
    transaction.wait_for_confirmation(client, txid, 10)

    print("Opting app into USDC with foreign_assets...")
    params = client.suggested_params()
    optin = transaction.ApplicationOptInTxn(addr, params, APP_ID, foreign_assets=[10458941])
    txid2 = client.send_transaction(optin.sign(sk))
    print(f"Optin Tx: {txid2}")
    transaction.wait_for_confirmation(client, txid2, 10)

    print("DONE - App fixed")
    print(f"APP_ID={APP_ID}")
    print(f"APP_ADDRESS={APP_ADDRESS}")

if __name__ == "__main__":
    main()