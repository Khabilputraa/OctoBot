import functools
import typing

import octobot_commons.tentacles_management as tentacles_management
import octobot_trading.blockchain_wallets.blockchain_wallet as blockchain_wallet
import octobot_trading.blockchain_wallets.blockchain_wallet_parameters as blockchain_wallet_parameters

if typing.TYPE_CHECKING:
    import octobot_trading.exchanges


@functools.lru_cache(maxsize=1)
def get_blockchain_wallet_class_by_blockchain() -> dict[str, type[blockchain_wallet.BlockchainWallet]]:
    return {
        wallet_class.BLOCKCHAIN: wallet_class 
        for wallet_class in tentacles_management.get_all_classes_from_parent(blockchain_wallet.BlockchainWallet)
    }


def create_blockchain_wallet(
    parameters: blockchain_wallet_parameters.BlockchainWalletParameters,
    trader: typing.Optional["octobot_trading.exchanges.Trader"],
) -> blockchain_wallet.BlockchainWallet:

    blockchain_wallet_class = None
    try:
        blockchain_wallet_class = get_blockchain_wallet_class_by_blockchain()[
            parameters.blockchain_descriptor.blockchain
        ]
        try:
            return blockchain_wallet_class(parameters)
        except TypeError:
            # trader arg is required for this wallet
            return blockchain_wallet_class(parameters, trader=trader)
    except KeyError as err:
        raise ValueError(
            f"Blockchain {parameters.blockchain_descriptor.blockchain} not supported"
        ) from err
