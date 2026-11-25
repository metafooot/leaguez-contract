# Deploy Leaguezz contract to Algorand Testnet
# 1. pip install pyteal algosdk
# 2. Set env: export DEPLOYER_MNEMONIC="your 25 words"
# 3. python deploy.py
# Output will print NEW App ID + App Address - paste those into LeaguezzContract.java (Android)
import os, sys
sys.path.insert(0, ".")  # contract.py is in same folder
from contract import approval, clear
from pyteal import compileTeal, Mode
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import ApplicationCreateTxn, PaymentTxn, wait_for_confirmation

ALGOD = "https://testnet-api.algonode.cloud"
# Fund app with 1 ALGO for boxes + inner txns
FUND_AMOUNT = 1_000_000

def main():
    m = os.environ.get("DEPLOYER_MNEMONIC", "").strip()
    if not m:
        print("ERROR: Set DEPLOYER_MNEMONIC env var first")
        print('  export DEPLOYER_MNEMONIC="word1 word2 ... word25"')
        return
    sk = mnemonic.to_private_key(m)
    addr = account.address_from_private_key(sk)
    print("Deployer:", addr)
    client = algod.AlgodClient("", ALGOD)
    params = client.suggested_params()
    approval_teal = compileTeal(approval(), mode=Mode.Application, version=8)
    clear_teal = compileTeal(clear(), mode=Mode.Application, version=8)
    # Compile on node
    comp_approval = client.compile(approval_teal)
    comp_clear = client.compile(clear_teal)
    # Create app - global 1 uint (bet_count), local 0, boxes needed (box refs are per-call, not in schema)
    txn = ApplicationCreateTxn(
        sender=addr,
        sp=params,
        on_complete=0,  # NoOp
        approval_program=bytes.fromhex(comp_approval["result"]),
        clear_program=bytes.fromhex(comp_clear["result"]),
        global_schema=(1, 0),  # 1 uint: bet_count
        local_schema=(0, 0),
        boxes=[(0, b"")],  # placeholder, real boxes are per-call
    )
    signed = txn.sign(sk)
    txid = client.send_transaction(signed)
    print("Create tx:", txid)
    res = wait_for_confirmation(client, txid, 10)
    app_id = res["application-index"]
    # App address = derived from app id
    from algosdk.logic import address as logic_address
    app_addr = logic_address(app_id)
    print(f"\n=== DONE ===")
    print(f"New App ID: {app_id}")
    print(f"New App Address: {app_addr}")
    print(f"\nPaste into LeaguezzContract.java:")
    print(f"  TESTNET_APP_ID = {app_id}L;")
    print(f'  TESTNET_APP_ADDRESS = "{app_addr}";')
    # Fund app so it can pay box rent + inner txn fees
    print("\nFunding app with 1 ALGO...")
    params2 = client.suggested_params()
    fund = PaymentTxn(addr, params2, app_addr, FUND_AMOUNT)
    txid2 = client.send_transaction(fund.sign(sk))
    wait_for_confirmation(client, txid2, 10)
    print("Funded. App is ready. Test $0.30 create in app.")

if __name__ == "__main__":
    main()
