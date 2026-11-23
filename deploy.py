"""
Leaguezz - GitHub Deploy
Deploys leaguezz_contract.teal to Algorand Testnet.
Mnemonic comes ONLY from GitHub Secret DEPLOYER_MNEMONIC - never in code, never in chat.
Run in GitHub Actions: Actions > Deploy Leaguezz > Run workflow
Prints NEW App ID + App Address in logs - copy them, they stay in logs.
"""
import os
import base64
from algosdk import account, mnemonic, transaction
from algosdk.v2client import algod

ALGOD = "https://testnet-api.algonode.cloud"
USDC_ID = 10458941

def main():
    seed = os.environ.get("DEPLOYER_MNEMONIC", "").strip()
    if not seed:
        raise SystemExit("ERROR: DEPLOYER_MNEMONIC secret is empty. Add it in GitHub > Settings > Secrets > Actions.")
    # Support both 25 words and base64 private key
    if len(seed.split()) == 25:
        sk = mnemonic.to_private_key(seed)
        addr = account.address_from_private_key(sk)
    else:
        # Assume base64 private key
        sk = base64.b64decode(seed)
        addr = account.address_from_private_key(sk)
    print(f"Deployer: {addr}")

    client = algod.AlgodClient("", ALGOD)
    with open("leaguezz_contract.teal", "r") as f:
        teal = f.read()

    print("Compiling approval...")
    approval = client.compile(teal)["result"]
    approval_prog = base64.b64decode(approval)
    print("Compiling clear...")
    clear = client.compile("#pragma version 8\nint 1\nreturn")["result"]
    clear_prog = base64.b64decode(clear)

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
    app_addr = transaction.logic.address_from_program(approval_prog)  # placeholder, replaced below
    # Real app address:
    from algosdk import logic
    import hashlib
    # Algorand app address = SHA256("appID" + uint64(app_id))
    import struct
    h = hashlib.sha256(b"appID" + struct.pack(">Q", app_id)).digest()
    from algosdk.encoding import encode_address
    app_addr = encode_address(h)
    print(f"APP_ADDRESS={app_addr}")
    print("Funding app 1 ALGO...")
    params = client.suggested_params()
    fund = transaction.PaymentTxn(addr, params, app_addr, 1_000_000)
    client.send_transaction(fund.sign(sk))
    transaction.wait_for_confirmation(client, fund.get_txid(), 10)
    print("Opting app into USDC...")
    params = client.suggested_params()
    optin = transaction.ApplicationOptInTxn(addr, params, app_id)
    client.send_transaction(optin.sign(sk))
    transaction.wait_for_confirmation(client, optin.get_txid(), 10)
    print("DONE")
    print(f"NEW APP ID: {app_id}")
    print(f"NEW APP ADDRESS: {app_addr}")
    print("Copy App ID into LeaguezzContract.java TESTNET_APP_ID once, Rebuild.")

if __name__ == "__main__":
    main()
