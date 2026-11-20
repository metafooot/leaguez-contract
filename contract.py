from pyteal import *

# Leaguezz - P2P Premier League betting
# Box layout (83 bytes):
# 0-31 creator (32), 32 creator_pick (1), 33-40 stake (8)
# 41-72 joiner (32), 73 joiner_pick (1), 74 status (1), 75-82 created_at (8)
# Pick: 0=HOME, 1=DRAW, 2=AWAY
# Status: 0=OPEN, 1=MATCHED, 2=SETTLED, 3=REFUNDED
# Fee locked at 10%, stored in global state. Update does NOT change global state.

def approval_program():
    FEE = Bytes("fee")
    BET_COUNT = Bytes("bet_count")
    ACTIVE = Bytes("active_bets")
    USDC = Bytes("usdc_id")
    CREATOR = Bytes("creator")
    ORACLE = Bytes("oracle")
    FEE_ADDR = Bytes("fee_addr")

    def one_byte(x):
        return Extract(Itob(x), Int(7), Int(1))

    def handle_creation():
        return Seq([
            App.globalPut(FEE, Int(10)),
            App.globalPut(BET_COUNT, Int(0)),
            App.globalPut(ACTIVE, Int(0)),
            # TestNet USDC. Change to 31566704 for MainNet
            App.globalPut(USDC, Int(10458941)),
            App.globalPut(CREATOR, Txn.sender()),
            App.globalPut(ORACLE, Txn.sender()),
            App.globalPut(FEE_ADDR, Txn.sender()),
            Return(Int(1)),
        ])

    def handle_opt_in():
        # Opt contract into USDC so it can hold USDC
        return Seq([
            Assert(Txn.sender() == App.globalGet(CREATOR)),
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(USDC),
                TxnField.asset_amount: Int(0),
                TxnField.asset_receiver: Global.current_application_address(),
            }),
            InnerTxnBuilder.Submit(),
            Return(Int(1)),
        ])

    def handle_create():
        pick_str = Txn.application_args[1]
        stake = Btoi(Txn.application_args[2])
        pick_code = If(
            pick_str == Bytes("HOME"), Int(0),
            If(pick_str == Bytes("DRAW"), Int(1), Int(2))
        )
        bet_id = App.globalGet(BET_COUNT)
        box_key = Itob(bet_id)
        return Seq([
            Assert(Txn.application_args.length() == Int(3)),
            Assert(pick_str == Bytes("HOME") or pick_str == Bytes("DRAW") or pick_str == Bytes("AWAY")),
            Assert(stake >= Int(1000000)), # $1
            Assert(stake <= Int(1000000000)), # $1000
            Assert(Global.group_size() == Int(2)),
            Assert(Gtxn[1].type_enum() == TxnType.AssetTransfer),
            Assert(Gtxn[1].sender() == Txn.sender()),
            Assert(Gtxn[1].asset_receiver() == Global.current_application_address()),
            Assert(Gtxn[1].xfer_asset() == App.globalGet(USDC)),
            Assert(Gtxn[1].asset_amount() == stake),
            Assert(App.box_exists(box_key) == Int(0)),
            App.box_put(
                box_key,
                Concat(
                    Txn.sender(),
                    one_byte(pick_code),
                    Itob(stake),
                    BytesZero(Int(32)),
                    one_byte(Int(255)),
                    one_byte(Int(0)),
                    Itob(Global.latest_timestamp()),
                )
            ),
            App.globalPut(BET_COUNT, bet_id + Int(1)),
            App.globalPut(ACTIVE, App.globalGet(ACTIVE) + Int(1)),
            Return(Int(1)),
        ])

    def handle_join():
        bet_id = Btoi(Txn.application_args[1])
        pick_str = Txn.application_args[2]
        box_key = Itob(bet_id)
        creator = App.box_extract(box_key, Int(0), Int(32))
        creator_pick = Btoi(App.box_extract(box_key, Int(32), Int(1)))
        stake = Btoi(App.box_extract(box_key, Int(33), Int(8)))
        status = Btoi(App.box_extract(box_key, Int(74), Int(1)))
        pick_code = If(
            pick_str == Bytes("HOME"), Int(0),
            If(pick_str == Bytes("DRAW"), Int(1), Int(2))
        )
        return Seq([
            Assert(Txn.application_args.length() == Int(3)),
            Assert(pick_str == Bytes("HOME") or pick_str == Bytes("DRAW") or pick_str == Bytes("AWAY")),
            Assert(App.box_exists(box_key) == Int(1)),
            Assert(status == Int(0)), # OPEN only
            Assert(Txn.sender() != creator), # cannot join own bet
            Assert(pick_code != creator_pick), # must pick different outcome
            Assert(Global.group_size() == Int(2)),
            Assert(Gtxn[1].type_enum() == TxnType.AssetTransfer),
            Assert(Gtxn[1].sender() == Txn.sender()),
            Assert(Gtxn[1].asset_receiver() == Global.current_application_address()),
            Assert(Gtxn[1].xfer_asset() == App.globalGet(USDC)),
            Assert(Gtxn[1].asset_amount() == stake),
            App.box_put(
                box_key,
                Concat(
                    App.box_extract(box_key, Int(0), Int(32)),
                    App.box_extract(box_key, Int(32), Int(1)),
                    App.box_extract(box_key, Int(33), Int(8)),
                    Txn.sender(),
                    one_byte(pick_code),
                    one_byte(Int(1)), # MATCHED
                    App.box_extract(box_key, Int(75), Int(8)),
                )
            ),
            Return(Int(1)),
        ])

    def handle_settle():
        bet_id = Btoi(Txn.application_args[1])
        result_str = Txn.application_args[2]
        box_key = Itob(bet_id)
        creator = App.box_extract(box_key, Int(0), Int(32))
        creator_pick = Btoi(App.box_extract(box_key, Int(32), Int(1)))
        stake = Btoi(App.box_extract(box_key, Int(33), Int(8)))
        joiner = App.box_extract(box_key, Int(41), Int(32))
        joiner_pick = Btoi(App.box_extract(box_key, Int(73), Int(1)))
        status = Btoi(App.box_extract(box_key, Int(74), Int(1)))
        result_code = If(
            result_str == Bytes("HOME"), Int(0),
            If(result_str == Bytes("DRAW"), Int(1), Int(2))
        )
        total = stake * Int(2)
        fee_amount = total / Int(10) # 10%
        winner_amount = total - fee_amount
        is_creator_win = And(result_code == creator_pick, result_code != joiner_pick)
        is_joiner_win = And(result_code == joiner_pick, result_code != creator_pick)
        is_winner = Or(is_creator_win, is_joiner_win)
        winner_addr = If(is_creator_win, creator, joiner)
        return Seq([
            Assert(Txn.application_args.length() == Int(3)),
            Assert(result_str == Bytes("HOME") or result_str == Bytes("DRAW") or result_str == Bytes("AWAY")),
            Assert(Txn.sender() == App.globalGet(ORACLE)), # only oracle, 【entity-GitHub¦canonical_name=GitHub】 + 【entity-ESPN¦canonical_name=ESPN】
            Assert(App.box_exists(box_key) == Int(1)),
            Assert(status == Int(1)), # MATCHED only, no double settle
            If(
                is_winner,
                Seq([
                    # Winner gets 90%, Leaguezz gets 10%
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: App.globalGet(USDC),
                        TxnField.asset_amount: winner_amount,
                        TxnField.asset_receiver: winner_addr,
                    }),
                    InnerTxnBuilder.Next(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: App.globalGet(USDC),
                        TxnField.asset_amount: fee_amount,
                        TxnField.asset_receiver: App.globalGet(FEE_ADDR),
                    }),
                    InnerTxnBuilder.Submit(),
                    App.box_put(
                        box_key,
                        Concat(
                            App.box_extract(box_key, Int(0), Int(32)),
                            App.box_extract(box_key, Int(32), Int(1)),
                            App.box_extract(box_key, Int(33), Int(8)),
                            App.box_extract(box_key, Int(41), Int(32)),
                            App.box_extract(box_key, Int(73), Int(1)),
                            one_byte(Int(2)), # SETTLED
                            App.box_extract(box_key, Int(75), Int(8)),
                        )
                    ),
                    App.globalPut(ACTIVE, App.globalGet(ACTIVE) - Int(1)),
                ]),
                Seq([
                    # No winner: Draw with no Draw bettor, or third outcome. Refund both.
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: App.globalGet(USDC),
                        TxnField.asset_amount: stake,
                        TxnField.asset_receiver: creator,
                    }),
                    InnerTxnBuilder.Next(),
                    InnerTxnBuilder.SetFields({
                        TxnField.type_enum: TxnType.AssetTransfer,
                        TxnField.xfer_asset: App.globalGet(USDC),
                        TxnField.asset_amount: stake,
                        TxnField.asset_receiver: joiner,
                    }),
                    InnerTxnBuilder.Submit(),
                    App.box_put(
                        box_key,
                        Concat(
                            App.box_extract(box_key, Int(0), Int(32)),
                            App.box_extract(box_key, Int(32), Int(1)),
                            App.box_extract(box_key, Int(33), Int(8)),
                            App.box_extract(box_key, Int(41), Int(32)),
                            App.box_extract(box_key, Int(73), Int(1)),
                            one_byte(Int(3)), # REFUNDED
                            App.box_extract(box_key, Int(75), Int(8)),
                        )
                    ),
                    App.globalPut(ACTIVE, App.globalGet(ACTIVE) - Int(1)),
                ])
            ),
            Return(Int(1)),
        ])

    def handle_refund():
        bet_id = Btoi(Txn.application_args[1])
        box_key = Itob(bet_id)
        creator = App.box_extract(box_key, Int(0), Int(32))
        stake = Btoi(App.box_extract(box_key, Int(33), Int(8)))
        joiner = App.box_extract(box_key, Int(41), Int(32))
        status = Btoi(App.box_extract(box_key, Int(74), Int(1)))
        created_at = Btoi(App.box_extract(box_key, Int(75), Int(8)))
        return Seq([
            Assert(Txn.application_args.length() == Int(2)),
            Assert(App.box_exists(box_key) == Int(1)),
            Assert(status == Int(1)), # MATCHED only
            Assert(Global.latest_timestamp() > created_at + Int(86400)), # 24h no result
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(USDC),
                TxnField.asset_amount: stake,
                TxnField.asset_receiver: creator,
            }),
            InnerTxnBuilder.Next(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(USDC),
                TxnField.asset_amount: stake,
                TxnField.asset_receiver: joiner,
            }),
            InnerTxnBuilder.Submit(),
            App.box_put(
                box_key,
                Concat(
                    App.box_extract(box_key, Int(0), Int(32)),
                    App.box_extract(box_key, Int(32), Int(1)),
                    App.box_extract(box_key, Int(33), Int(8)),
                    App.box_extract(box_key, Int(41), Int(32)),
                    App.box_extract(box_key, Int(73), Int(1)),
                    one_byte(Int(3)), # REFUNDED
                    App.box_extract(box_key, Int(75), Int(8)),
                )
            ),
            App.globalPut(ACTIVE, App.globalGet(ACTIVE) - Int(1)),
            Return(Int(1)),
        ])

    on_creation = handle_creation()
    on_update = Seq([
        Assert(Txn.sender() == App.globalGet(CREATOR)),
        Assert(App.globalGet(ACTIVE) == Int(0)), # update only when no active bets
        Return(Int(1)),
    ])
    on_delete = Return(Int(0)) # never allow delete, protects funds
    on_optin = Return(Int(1))
    on_closeout = Return(Int(1))
    on_clear = Return(Int(1))

    on_noop = Cond(
        [Txn.application_args[0] == Bytes("create"), handle_create()],
        [Txn.application_args[0] == Bytes("join"), handle_join()],
        [Txn.application_args[0] == Bytes("settle"), handle_settle()],
        [Txn.application_args[0] == Bytes("refund"), handle_refund()],
        [Txn.application_args[0] == Bytes("opt_in"), handle_opt_in()],
    )

    program = Cond(
        [Txn.application_id() == Int(0), on_creation],
        [Txn.on_completion() == OnComplete.UpdateApplication, on_update],
        [Txn.on_completion() == OnComplete.DeleteApplication, on_delete],
        [Txn.on_completion() == OnComplete.OptIn, on_optin],
        [Txn.on_completion() == OnComplete.CloseOut, on_closeout],
        [Txn.on_completion() == OnComplete.ClearState, on_clear],
        [Txn.on_completion() == OnComplete.NoOp, on_noop],
    )
    return program

def clear_program():
    return Return(Int(1))
