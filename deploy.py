# Deploy Leaguezz contract to Algorand Testnet
import os, sys, base64
sys.path.insert(0, ".")
from contract import approval, clear
from pyteal import compileTeal, Mode
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import ApplicationCreateTxn, ApplicationCallTxn, PaymentTxn, wait_for_confirmation, StateSchema

ALGOD = "https://testnet-api.algonode.cloud"
FUND_AMOUNT = 5_000_000
USDC_ID = 10458941

def main():
    m = os.environ.get("DEPLOYER_MNEMONIC", "").strip()
    if not m:
        print("ERROR: Set DEPLOYER_MNEMONIC env var first")
        return
    sk = mnemonic.to_private_key(m)
    addr = account.address_from_private_key(sk)
    print("Deployer:", addr)
    client = algod.AlgodClient("", ALGOD)
    params = client.suggested_params()
    params.fee = 3000
    params.flat_fee = True
    approval_teal = compileTeal(approval(), mode=Mode.Application, version=8)
    clear_teal = compileTeal(clear(), mode=Mode.Application, version=8)
    comp_approval = client.compile(approval_teal)
    comp_clear = client.compile(clear_teal)
    approval_prog = base64.b64decode(comp_approval["result"])
    clear_prog = base64.b64decode(comp_clear["result"])
    txn = ApplicationCreateTxn(
        sender=addr,
        sp=params,
        on_complete=0,
        approval_program=approval_prog,
        clear_program=clear_prog,
        global_schema=StateSchema(1, 0),
        local_schema=StateSchema(0, 0),
    )
    signed = txn.sign(sk)
    txid = client.send_transaction(signed)
    print("Create tx:", txid)
    res = wait_for_confirmation(client, txid, 10)
    app_id = res["application-index"]
    try:
        from algosdk.logic import address as logic_address
        app_addr = logic_address(app_id)
    except Exception:
        from algosdk import encoding
        import hashlib
        app_addr = encoding.encode_address(hashlib.new('sha512_256', b'appID' + app_id.to_bytes(8, 'big')).digest())
    print(f"New App ID: {app_id}")
    print(f"New App Address: {app_addr}")
    print("Funding app with 5 ALGO...")
    params2 = client.suggested_params()
    params2.fee = 1000
    params2.flat_fee = True
    fund = PaymentTxn(addr, params2, app_addr, FUND_AMOUNT)
    txid2 = client.send_transaction(fund.sign(sk))
    wait_for_confirmation(client, txid2, 10)
    print("Funded.")
    print("Opting app into USDC...")
    params3 = client.suggested_params()
    params3.fee = 2000
    params3.flat_fee = True
    optin = ApplicationCallTxn(
        sender=addr,
        sp=params3,
        index=app_id,
        on_complete=0,
        app_args=[b"optin"],
        foreign_assets=[USDC_ID],
    )
    txid3 = client.send_transaction(optin.sign(sk))
    wait_for_confirmation(client, txid3, 10)
    print("Opted into USDC.")
    print(f"\n=== DONE ===")
    print(f"New App ID: {app_id}")
    print(f"New App Address: {app_addr}")
    print(f"\nPaste into LeaguezzContract.java:")
    print(f"  TESTNET_APP_ID = {app_id}L;")
    print(f'  TESTNET_APP_ADDRESS = "{app_addr}";')
    print("App is ready. Test $0.30 create in app.")

if __name__ == "__main__":
    main()