# Leaguezz - GitHub contract - V22
# $0.30 min, $1000 max, 5% fee, HOME/DRAW/AWAY, refund on third outcome
# Deploy to Testnet, then paste new App ID + App Address into LeaguezzContract.java (Android)
# Box layout (96 bytes) - MUST match Android parseBet() first layout:
#   0-31  : creator address (32 bytes)
#   32-63 : joiner address (32 bytes, zeros if none)
#   64-71 : creatorPick uint64 (0=HOME, 1=DRAW, 2=AWAY)
#   72-79 : joinerPick uint64 (255 = none)
#   80-87 : stakeMicro uint64
#   88-95 : status uint64 (0=OPEN, 1=MATCHED, 2=SETTLED, 3=REFUNDED)
# Global: bet_count uint64
# Methods called by Android (LeaguezzContract.java):
#   create : args ["create", pickStr, stakeMicro(8 bytes)] + Group[1] USDC pay to app
#   join   : args ["join", betId(8 bytes), pickStr] + Group[1] USDC pay to app
#   settle : args ["settle", betId(8 bytes)] - contract picks random result, pays winner or refunds
#   refund : args ["refund", betId(8 bytes)] - refund open/matched bet

from pyteal import *

USDC_ID = Int(10458941)  # Testnet USDC. For Mainnet change to 31566704
MIN_STAKE = Int(300000)      # $0.30 - V22, was 1000000 ($1)
MAX_STAKE = Int(1000000000)  # $1000
NO_PICK = Int(255)

def pick_from_str(s):
    # s is bytes "HOME" / "DRAW" / "AWAY"
    return If(s == Bytes("HOME"), Int(0),
           If(s == Bytes("DRAW"), Int(1),
           If(s == Bytes("AWAY"), Int(2), Int(99))))

def is_valid_pick(p):
    return And(p >= Int(0), p <= Int(2))

def approval():
    # ---- Creation ----
    on_create = Seq(
        # Opt app into USDC so it can hold / pay USDC (inner txn, 0 amount to itself)
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: USDC_ID,
            TxnField.asset_receiver: Global.current_application_address(),
            TxnField.asset_amount: Int(0),
            TxnField.fee: Int(0),
        }),
        InnerTxnBuilder.Submit(),
        App.globalPut(Bytes("bet_count"), Int(0)),
        Approve(),
    )

    # ---- CREATE ----
    create_pick = pick_from_str(Txn.application_args[1])
    create_stake = Btoi(Txn.application_args[2])
    create_bet_id = App.globalGet(Bytes("bet_count"))
    create_box = Itob(create_bet_id)
    create_value = Concat(
        Txn.sender(),
        BytesZero(Int(32)),
        Itob(create_pick),
        Itob(NO_PICK),
        Itob(create_stake),
        Itob(Int(0)),
    )
    on_create_bet = Seq(
        Assert(Txn.application_args.length() == Int(3)),
        Assert(is_valid_pick(create_pick)),
        Assert(And(create_stake >= MIN_STAKE, create_stake <= MAX_STAKE)),
        Assert(Global.group_size() == Int(2)),
        # Group[1] must be USDC pay of exact stake to app
        Assert(Gtxn[1].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[1].xfer_asset() == USDC_ID),
        Assert(Gtxn[1].sender() == Txn.sender()),
        Assert(Gtxn[1].asset_receiver() == Global.current_application_address()),
        Assert(Gtxn[1].asset_amount() == create_stake),
        # Box must not exist yet
        Assert(Not(BoxLen(create_box).hasValue())),
        Assert(BoxCreate(create_box, Int(96))),
        BoxPut(create_box, create_value),
        App.globalPut(Bytes("bet_count"), create_bet_id + Int(1)),
        Approve(),
    )

    # ---- JOIN ----
    join_bet_id = Btoi(Txn.application_args[1])
    join_pick = pick_from_str(Txn.application_args[2])
    join_box = Itob(join_bet_id)
    join_box_val = BoxGet(join_box)
    join_creator = Extract(join_box_val.value(), Int(0), Int(32))
    join_status = Btoi(Extract(join_box_val.value(), Int(88), Int(8)))
    join_creator_pick = Btoi(Extract(join_box_val.value(), Int(64), Int(8)))
    join_stake = Btoi(Extract(join_box_val.value(), Int(80), Int(8)))
    on_join = Seq(
        Assert(Txn.application_args.length() == Int(3)),
        Assert(is_valid_pick(join_pick)),
        Assert(join_box_val.hasValue()),
        Assert(join_status == Int(0)),  # only OPEN
        Assert(Txn.sender() != join_creator),  # joiner != creator
        Assert(join_pick != join_creator_pick),  # must pick a different outcome
        Assert(Global.group_size() == Int(2)),
        Assert(Gtxn[1].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[1].xfer_asset() == USDC_ID),
        Assert(Gtxn[1].sender() == Txn.sender()),
        Assert(Gtxn[1].asset_receiver() == Global.current_application_address()),
        Assert(Gtxn[1].asset_amount() == join_stake),
        # Update box: joiner + joinerPick + status=1
        BoxReplace(join_box, Int(32), Txn.sender()),
        BoxReplace(join_box, Int(72), Itob(join_pick)),
        BoxReplace(join_box, Int(88), Itob(Int(1))),
        Approve(),
    )

    # ---- SETTLE (auto, random) ----
    settle_bet_id = Btoi(Txn.application_args[1])
    settle_box = Itob(settle_bet_id)
    settle_val = BoxGet(settle_box)
    settle_creator = Extract(settle_val.value(), Int(0), Int(32))
    settle_joiner = Extract(settle_val.value(), Int(32), Int(32))
    settle_creator_pick = Btoi(Extract(settle_val.value(), Int(64), Int(8)))
    settle_joiner_pick = Btoi(Extract(settle_val.value(), Int(72), Int(8)))
    settle_stake = Btoi(Extract(settle_val.value(), Int(80), Int(8)))
    settle_status = Btoi(Extract(settle_val.value(), Int(88), Int(8)))
    # Random result: (timestamp + betId + round) % 3 - no admin picks it
    settle_result = (Global.latest_timestamp() + settle_bet_id + Global.round()) % Int(3)
    settle_winner_amount = settle_stake * Int(190) / Int(100)  # 2x stake * 95% = $0.57 on $0.30
    on_settle = Seq(
        Assert(Txn.application_args.length() == Int(2)),
        Assert(settle_val.hasValue()),
        Assert(settle_status == Int(1)),  # only MATCHED
        Assert(Global.group_size() == Int(1)),
        If(settle_result == settle_creator_pick,
            Seq(
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: USDC_ID,
                    TxnField.asset_receiver: settle_creator,
                    TxnField.asset_amount: settle_winner_amount,
                    TxnField.fee: Int(0),
                }),
                InnerTxnBuilder.Submit(),
                BoxReplace(settle_box, Int(88), Itob(Int(2))),
                Approve(),
            ),
            If(settle_result == settle_joiner_pick,
                Seq(
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: USDC_ID,
                        TxnField.asset_receiver: settle_joiner,
                        TxnField.asset_amount: settle_winner_amount,
                        TxnField.fee: Int(0),
                    }),
                    InnerTxnBuilder.Submit(),
                    BoxReplace(settle_box, Int(88), Itob(Int(2))),
                    Approve(),
                ),
                # Third outcome: nobody picked it -> refund both, no fee
                Seq(
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: USDC_ID,
                        TxnField.asset_receiver: settle_creator,
                        TxnField.asset_amount: settle_stake,
                        TxnField.fee: Int(0),
                    }),
                    InnerTxnBuilder.Submit(),
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: USDC_ID,
                        TxnField.asset_receiver: settle_joiner,
                        TxnField.asset_amount: settle_stake,
                        TxnField.fee: Int(0),
                    }),
                    InnerTxnBuilder.Submit(),
                    BoxReplace(settle_box, Int(88), Itob(Int(3))),
                    Approve(),
                ),
            ),
        ),
    )

    # ---- REFUND ----
    refund_bet_id = Btoi(Txn.application_args[1])
    refund_box = Itob(refund_bet_id)
    refund_val = BoxGet(refund_box)
    refund_creator = Extract(refund_val.value(), Int(0), Int(32))
    refund_joiner = Extract(refund_val.value(), Int(32), Int(32))
    refund_stake = Btoi(Extract(refund_val.value(), Int(80), Int(8)))
    refund_status = Btoi(Extract(refund_val.value(), Int(88), Int(8)))
    on_refund = Seq(
        Assert(Txn.application_args.length() == Int(2)),
        Assert(refund_val.hasValue()),
        Assert(Or(refund_status == Int(0), refund_status == Int(1))),
        Assert(Global.group_size() == Int(1)),
        If(refund_status == Int(0),
            Seq(
                Assert(Txn.sender() == refund_creator),  # only creator can refund OPEN
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: USDC_ID,
                    TxnField.asset_receiver: refund_creator,
                    TxnField.asset_amount: refund_stake,
                    TxnField.fee: Int(0),
                }),
                InnerTxnBuilder.Submit(),
                BoxReplace(refund_box, Int(88), Itob(Int(3))),
                Approve(),
            ),
            Seq(
                Assert(Or(Txn.sender() == refund_creator, Txn.sender() == refund_joiner)),
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: USDC_ID,
                    TxnField.asset_receiver: refund_creator,
                    TxnField.asset_amount: refund_stake,
                    TxnField.fee: Int(0),
                }),
                InnerTxnBuilder.Submit(),
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: USDC_ID,
                    TxnField.asset_receiver: refund_joiner,
                    TxnField.asset_amount: refund_stake,
                    TxnField.fee: Int(0),
                }),
                InnerTxnBuilder.Submit(),
                BoxReplace(refund_box, Int(88), Itob(Int(3))),
                Approve(),
            ),
        ),
    )

    method = Txn.application_args[0]
    program = Cond(
        [Txn.application_id() == Int(0), on_create],
        [Txn.on_completion() == OnComplete.OptIn, Approve()],
        [Txn.on_completion() == OnComplete.CloseOut, Approve()],
        [Txn.on_completion() == OnComplete.UpdateApplication, Reject()],  # no admin, no update
        [Txn.on_completion() == OnComplete.DeleteApplication, Reject()],  # no admin, no delete
        [Txn.on_completion() == OnComplete.ClearState, Approve()],
        [method == Bytes("create"), on_create_bet],
        [method == Bytes("join"), on_join],
        [method == Bytes("settle"), on_settle],
        [method == Bytes("refund"), on_refund],
    )
    return program

def clear():
    return Approve()

if __name__ == "__main__":
    import sys
    # Usage: python contract.py > approval.teal  (prints TEAL)
    print(compileTeal(approval(), mode=Mode.Application, version=8))
    print("---CLEAR---", file=sys.stderr)
    print(compileTeal(clear(), mode=Mode.Application, version=8), file=sys.stderr)