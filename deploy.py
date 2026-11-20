import os
import base64
from algosdk import account, mnemonic, transaction
from algosdk.v2client import algod
from pyteal import compileTeal, Mode
from contract import approval_program, clear_program

def main():
    mn = os.environ.get("DEPLOYER_MNEMONIC", "")
    if not mn:
        print("Missing DEPLOYER_MNEMONIC secret")
        return
    private_key = mnemonic.to_private_key(mn)
    address = account.address_from_private_key(private_key)
    print("Deployer:", address)

    # TestNet. For MainNet change to https://mainnet-api.algonode.cloud
    algod_client = algod.AlgodClient("", "https://testnet-api.algonode.cloud")

    approval_teal = compileTeal(approval_program(), mode=Mode.Application, version=8)
    clear_teal = compileTeal(clear_program(), mode=Mode.Application, version=8)
    approval_compiled = algod_client.compile(approval_teal)
    clear_compiled = algod_client.compile(clear_teal)
    approval_bytes = base64.b64decode(approval_compiled["result"])
    clear_bytes = base64.b64decode(clear_compiled["result"])

    params = algod_client.suggested_params()
    # 4 uints: fee, bet_count, active_bets, usdc_id. 3 bytes: creator, oracle, fee_addr
    global_schema = transaction.StateSchema(num_uints=4, num_byte_slices=3)
    local_schema = transaction.StateSchema(num_uints=0, num_byte_slices=0)

    txn = transaction.ApplicationCreateTxn(
        sender=address,
        sp=params,
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval_bytes,
        clear_program=clear_bytes,
        global_schema=global_schema,
        local_schema=local_schema,
    )
    signed = txn.sign(private_key)
    txid = algod_client.send_transaction(signed)
    print("TXID:", txid)
    result = transaction.wait_for_confirmation(algod_client, txid, 10)
    app_id = result["application-index"]
    app_addr = transaction.logic.address(app_id)
    print("Deployed App ID:", app_id)
    print("Contract Address:", app_addr)

    # Fund contract with 1 ALGO for min balance + inner txn fees
    params2 = algod_client.suggested_params()
    fund_txn = transaction.PaymentTxn(
        sender=address, sp=params2, receiver=app_addr, amt=1000000
    )
    signed_fund = fund_txn.sign(private_key)
    txid2 = algod_client.send_transaction(signed_fund)
    transaction.wait_for_confirmation(algod_client, txid2, 10)
    print("Funded contract with 1 ALGO")

    # Opt contract into USDC
    params3 = algod_client.suggested_params()
    optin_txn = transaction.ApplicationCallTxn(
        sender=address, sp=params3, index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"opt_in"],
    )
    signed_optin = optin_txn.sign(private_key)
    txid3 = algod_client.send_transaction(signed_optin)
    transaction.wait_for_confirmation(algod_client, txid3, 10)
    print("Contract opted into USDC")

if __name__ == "__main__":
    main()
