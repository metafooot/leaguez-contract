import os
import base64
import struct
import hashlib
from algosdk import account, mnemonic, transaction
from algosdk.v2client import algod
from algosdk.encoding import encode_address

ALGOD = "https://testnet-api.algonode.cloud"

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
    client = algod.AlgodClient("", ALGOD)
    with open("leaguezz_contract.teal", "r") as f:
        teal = f.read()
    print("Compiling approval...")
    approval_prog = base64.b64decode(client.compile(teal)["result"])
    print("Compiling clear...")
    clear_prog = base64.b64decode(client.compile("#pragma version 8\nint 1\nreturn")["result"])
    params = client.suggested_params()
    print("Creating App...")
    txn = transaction.ApplicationCreateTxn(
        sender=addr,
        sp=params,
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval_prog,
        clear_program=clear_prog,
        global_schema=transaction.StateSchema(num_uints=1, num_byte_slices=0),
        local_schema=transaction.StateSchema(num_uints=0, num_byte_slices=0),
    )
    signed = txn.sign(sk)
    txid = client.send_transaction(signed)
    print(f"Create Tx: {txid}")
    result = transaction.wait_for_confirmation(client, txid, 10)
    app_id = result["application-index"]
    print(f"APP_ID={app_id}")
    h = hashlib.new('sha512_256', b"appID" + struct.pack(">Q", app_id)).digest()
    app_addr = encode_address(h)
    print(f"APP_ADDRESS={app_addr}")
    print("Funding app 1 ALGO...")
    params = client.suggested_params()
    fund = transaction.PaymentTxn(addr, params, app_addr, 1_000_000)
    client.send_transaction(fund.sign(sk))
    transaction.wait_for_confirmation(client, fund.get_txid(), 10)
    print("Opting app into USDC...")
    params = client.suggested_params()
    optin = transaction.ApplicationOptInTxn(addr, params, app_id, foreign_assets=[10458941])
    client.send_transaction(optin.sign(sk))
    transaction.wait_for_confirmation(client, optin.get_txid(), 10)
    print("DONE")
    print(f"NEW APP ID: {app_id}")
    print(f"NEW APP ADDRESS: {app_addr}")

if __name__ == "__main__":
    main()