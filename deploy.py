import os
import base64
import hashlib
from algosdk import account, mnemonic, encoding
from algosdk.v2client import algod
from algosdk import transaction
from pyteal import compileTeal, Mode
from contract import approval_program, clear_program

ALGOD_URL = "https://testnet-api.algonode.cloud"
USDC_TESTNET = 10458941

def compile_program(client, source):
    result = client.compile(source)
    return base64.b64decode(result["result"])

def wait(txid):
    return transaction.wait_for_confirmation(algod_client, txid, 10)

def get_app_address(app_id):
    # App address = checksum of b"appID" + app_id as 8-byte big-endian
    buf = b"appID" + app_id.to_bytes(8, "big")
    h = hashlib.sha256(buf).digest()
    return encoding.encode_address(h)

mnemonic_phrase = os.environ.get("DEPLOYER_MNEMONIC", "").strip()
if not mnemonic_phrase:
    raise SystemExit("Missing DEPLOYER_MNEMONIC secret")

private_key = mnemonic.to_private_key(mnemonic_phrase)
deployer = account.address_from_private_key(private_key)

algod_client = algod.AlgodClient("", ALGOD_URL)

print(f"Deployer: {deployer}")

approval_teal = compileTeal(approval_program(), mode=Mode.Application, version=8)
clear_teal = compileTeal(clear_program(), mode=Mode.Application, version=8)

approval_compiled = compile_program(algod_client, approval_teal)
clear_compiled = compile_program(algod_client, clear_teal)

sp = algod_client.suggested_params()

# Global: 4 ints (fee, bet_count, active, usdc) + 3 bytes (creator, oracle, fee_addr)
global_schema = transaction.StateSchema(num_uints=4, num_byte_slices=3)
local_schema = transaction.StateSchema(num_uints=0, num_byte_slices=0)

create_txn = transaction.ApplicationCreateTxn(
    sender=deployer,
    sp=sp,
    on_complete=transaction.OnComplete.NoOpOC,
    approval_program=approval_compiled,
    clear_program=clear_compiled,
    global_schema=global_schema,
    local_schema=local_schema,
    extra_pages=1,
)

signed = create_txn.sign(private_key)
txid = algod_client.send_transaction(signed)
confirmed = wait(txid)
app_id = confirmed["application-index"]
app_addr = get_app_address(app_id)

print("========================================")
print("LEAGUEZZ DEPLOYED - TESTNET")
print(f"APP_ID={app_id}")
print(f"APP_ADDRESS={app_addr}")
print(f"DEPLOYER={deployer}")
print("========================================")

with open("app_id.txt", "w") as f:
    f.write(f"APP_ID={app_id}\n")
    f.write(f"APP_ADDRESS={app_addr}\n")
    f.write(f"DEPLOYER={deployer}\n")
    f.write(f"USDC_TESTNET={USDC_TESTNET}\n")

# Fund app so it can opt-in to USDC (0.5 ALGO)
sp2 = algod_client.suggested_params()
fund_txn = transaction.PaymentTxn(deployer, sp2, app_addr, 500000)
signed_fund = fund_txn.sign(private_key)
txid2 = algod_client.send_transaction(signed_fund)
wait(txid2)
print("Funded app with 0.5 ALGO")

# Opt-in app to USDC
sp3 = algod_client.suggested_params()
optin_txn = transaction.ApplicationNoOpTxn(
    sender=deployer,
    sp=sp3,
    index=app_id,
    app_args=[b"opt_in"],
)
signed_optin = optin_txn.sign(private_key)
txid3 = algod_client.send_transaction(signed_optin)
wait(txid3)
print("App opted-in to USDC - READY")
print("========================================")
print(f"COPY THIS APP_ID: {app_id}")
print("========================================")
