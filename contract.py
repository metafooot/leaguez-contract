# Leaguezz - Algorand TestNet Contract (PyTeal)
# Fixes old App 776578156 which had: Assert(joiner == "HOME")
# New rule: Assert(joiner != creator)
# Picks: HOME=0, DRAW=1, AWAY=2
# Box layout (96 bytes, must match LeaguezzContract.java parseBet):
#   0..32  creator address (32)
#   32..64 joiner address (32, zeros if none)
#   64..72 creatorPick uint64
#   72..80 joinerPick uint64 (255 if none)
#   80..88 stakeMicro uint64
#   88..96 status uint64 (0=open, 1=joined, 2=settled, 3=refunded)
# Global: bet_count uint64
# Fee: winner gets 90% of pot, 10% stays in app

from pyteal import *

# USDC TestNet = 10458941, MainNet = 31566704 - set at deploy time
USDC_ID = Int(10458941)

def pick_from_string(s: Expr) -> Expr:
    return Cond(
        [s == Bytes("HOME"), Int(0)],
        [s == Bytes("DRAW"), Int(1)],
        [s == Bytes("AWAY"), Int(2)],
        [Int(1), Int(255)],  # invalid
    )

def is_valid_pick(p: Expr) -> Expr:
    return And(p >= Int(0), p <= Int(2))

def program():
    # ---- Common ----
    action = Txn.application_args[0]
    bet_count = App.globalGet(Bytes("bet_count"))

    # ---- CREATE: args = ["create", pickStr, stakeMicroBytes] + USDC pay ----
    # Group: [0]=AppCall, [1]=USDC transfer creator -> app
    create_pick = pick_from_string(Txn.application_args[1])
    create_stake = Btoi(Txn.application_args[2])
    create_bet_id = bet_count
    create_box_name = Itob(create_bet_id)
    create_box_value = Concat(
        Txn.sender(),
        BytesZero(Int(32)),  # joiner empty
        Itob(create_pick),
        Itob(Int(255)),     # joinerPick none
        Itob(create_stake),
        Itob(Int(0)),       # status 0 open
    )
    on_create = Seq(
        Assert(Txn.application_args.length() == Int(3)),
        Assert(is_valid_pick(create_pick)),
        Assert(And(create_stake >= Int(1000000), create_stake <= Int(1000000000))),  # $1 - $1000
        # Payment must be USDC, from creator to this app, exact stake
        Assert(Gtxn[1].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[1].xfer_asset() == USDC_ID),
        Assert(Gtxn[1].sender() == Txn.sender()),
        Assert(Gtxn[1].asset_receiver() == Global.current_application_address()),
        Assert(Gtxn[1].asset_amount() == create_stake),
        # Box must not exist yet
        (box_exists := App.box_length(create_box_name)),
        Assert(Not(box_exists.hasValue())),
        App.box_put(create_box_name, create_box_value),
        App.globalPut(Bytes("bet_count"), bet_count + Int(1)),
        Approve(),
    )

    # ---- JOIN: args = ["join", betIdBytes, pickStr] + USDC pay ----
    # THIS IS THE FIX: old contract had Assert(joinerPick == "HOME")
    # New: Assert(joinerPick != creatorPick)
    join_bet_id = Btoi(Txn.application_args[1])
    join_pick = pick_from_string(Txn.application_args[2])
    join_box_name = Itob(join_bet_id)
    join_box = App.box_get(join_box_name)
    join_creator = Extract(join_box.value(), Int(0), Int(32))
    join_creator_pick = Btoi(Extract(join_box.value(), Int(64), Int(8)))
    join_joiner_pick_old = Btoi(Extract(join_box.value(), Int(72), Int(8)))
    join_stake = Btoi(Extract(join_box.value(), Int(80), Int(8)))
    join_status = Btoi(Extract(join_box.value(), Int(88), Int(8)))
    join_new_value = Concat(
        join_creator,
        Txn.sender(),
        Itob(join_creator_pick),
        Itob(join_pick),
        Itob(join_stake),
        Itob(Int(1)),  # status 1 joined
    )
    on_join = Seq(
        Assert(Txn.application_args.length() == Int(3)),
        Assert(join_box.hasValue()),
        Assert(is_valid_pick(join_pick)),
        Assert(join_status == Int(0)),  # must be open
        Assert(Txn.sender() != join_creator),  # cannot join own bet
        # FIX: any different pick is allowed - HOME/DRAW/AWAY all work
        Assert(join_pick != join_creator_pick),
        # Payment must be USDC, exact same stake as creator
        Assert(Gtxn[1].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[1].xfer_asset() == USDC_ID),
        Assert(Gtxn[1].sender() == Txn.sender()),
        Assert(Gtxn[1].asset_receiver() == Global.current_application_address()),
        Assert(Gtxn[1].asset_amount() == join_stake),
        App.box_put(join_box_name, join_new_value),
        Approve(),
    )

    # ---- SETTLE: args = ["settle", betIdBytes, resultStr] ----
    # resultStr = HOME / DRAW / AWAY / CANCELLED
    # If result == creatorPick -> creator wins 90% of pot
    # If result == joinerPick -> joiner wins 90%
    # If result == nobody's pick (e.g. picks HOME/AWAY, result DRAW) -> refund both
    # If result == CANCELLED -> refund both
    settle_bet_id = Btoi(Txn.application_args[1])
    settle_result_str = Txn.application_args[2]
    settle_box_name = Itob(settle_bet_id)
    settle_box = App.box_get(settle_box_name)
    settle_creator = Extract(settle_box.value(), Int(0), Int(32))
    settle_joiner = Extract(settle_box.value(), Int(32), Int(32))
    settle_creator_pick = Btoi(Extract(settle_box.value(), Int(64), Int(8)))
    settle_joiner_pick = Btoi(Extract(settle_box.value(), Int(72), Int(8)))
    settle_stake = Btoi(Extract(settle_box.value(), Int(80), Int(8)))
    settle_status = Btoi(Extract(settle_box.value(), Int(88), Int(8)))
    settle_pot = settle_stake * Int(2)
    settle_payout = settle_pot * Int(90) / Int(100)  # 90%
    settle_result_pick = pick_from_string(settle_result_str)
    is_cancelled = settle_result_str == Bytes("CANCELLED")
    # Inner payouts
    pay_creator_win = Seq(
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: USDC_ID,
            TxnField.asset_receiver: settle_creator,
            TxnField.asset_amount: settle_payout,
            TxnField.fee: Int(0),
        }),
        InnerTxnBuilder.Submit(),
    )
    pay_joiner_win = Seq(
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: USDC_ID,
            TxnField.asset_receiver: settle_joiner,
            TxnField.asset_amount: settle_payout,
            TxnField.fee: Int(0),
        }),
        InnerTxnBuilder.Submit(),
    )
    pay_refund_both = Seq(
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
    )
    on_settle = Seq(
        Assert(Txn.application_args.length() == Int(3)),
        Assert(settle_box.hasValue()),
        Assert(settle_status == Int(1)),  # must be joined
        If(is_cancelled)
        .Then(Seq(
            pay_refund_both,
            App.box_put(settle_box_name, Concat(
                settle_creator, settle_joiner,
                Itob(settle_creator_pick), Itob(settle_joiner_pick),
                Itob(settle_stake), Itob(Int(3)),
            )),
            Approve(),
        ))
        .Else(Seq(
            Assert(is_valid_pick(settle_result_pick)),
            If(settle_result_pick == settle_creator_pick)
            .Then(Seq(
                pay_creator_win,
                App.box_put(settle_box_name, Concat(
                    settle_creator, settle_joiner,
                    Itob(settle_creator_pick), Itob(settle_joiner_pick),
                    Itob(settle_stake), Itob(Int(2)),
                )),
                Approve(),
            ))
            .ElseIf(settle_result_pick == settle_joiner_pick)
            .Then(Seq(
                pay_joiner_win,
                App.box_put(settle_box_name, Concat(
                    settle_creator, settle_joiner,
                    Itob(settle_creator_pick), Itob(settle_joiner_pick),
                    Itob(settle_stake), Itob(Int(2)),
                )),
                Approve(),
            ))
            .Else(Seq(
                # Third outcome nobody picked -> refund both, no fee
                pay_refund_both,
                App.box_put(settle_box_name, Concat(
                    settle_creator, settle_joiner,
                    Itob(settle_creator_pick), Itob(settle_joiner_pick),
                    Itob(settle_stake), Itob(Int(3)),
                )),
                Approve(),
            )),
        )),
    )

    # ---- REFUND: args = ["refund", betIdBytes] - only open bets, only creator ----
    refund_bet_id = Btoi(Txn.application_args[1])
    refund_box_name = Itob(refund_bet_id)
    refund_box = App.box_get(refund_box_name)
    refund_creator = Extract(refund_box.value(), Int(0), Int(32))
    refund_creator_pick = Btoi(Extract(refund_box.value(), Int(64), Int(8)))
    refund_joiner_pick = Btoi(Extract(refund_box.value(), Int(72), Int(8)))
    refund_stake = Btoi(Extract(refund_box.value(), Int(80), Int(8)))
    refund_status = Btoi(Extract(refund_box.value(), Int(88), Int(8)))
    on_refund = Seq(
        Assert(Txn.application_args.length() == Int(2)),
        Assert(refund_box.hasValue()),
        Assert(refund_status == Int(0)),
        Assert(Txn.sender() == refund_creator),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: USDC_ID,
            TxnField.asset_receiver: refund_creator,
            TxnField.asset_amount: refund_stake,
            TxnField.fee: Int(0),
        }),
        InnerTxnBuilder.Submit(),
        App.box_put(refund_box_name, Concat(
            refund_creator, BytesZero(Int(32)),
            Itob(refund_creator_pick), Itob(refund_joiner_pick),
            Itob(refund_stake), Itob(Int(3)),
        )),
        Approve(),
    )

    # ---- Router ----
    return Cond(
        [Txn.application_id() == Int(0), Seq(App.globalPut(Bytes("bet_count"), Int(0)), Approve())],
        [Txn.on_completion() == OnComplete.NoOp, Cond(
            [action == Bytes("create"), on_create],
            [action == Bytes("join"), on_join],
            [action == Bytes("settle"), on_settle],
            [action == Bytes("refund"), on_refund],
            [Int(1), Reject()],
        )],
        [Txn.on_completion() == OnComplete.OptIn, Approve()],
        [Txn.on_completion() == OnComplete.CloseOut, Approve()],
        [Txn.on_completion() == OnComplete.UpdateApplication, Reject()],
        [Txn.on_completion() == OnComplete.DeleteApplication, Reject()],
    )

if __name__ == "__main__":
    import sys
    prog = compileTeal(program(), mode=Mode.Application, version=8)
    open("leaguezz_contract.teal", "w").write(prog)
    print(prog)
