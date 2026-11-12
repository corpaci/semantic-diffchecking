"""Withheld requirement checks. Mount only in the evaluation container."""
import inspect
import unittest


def covers(*requirements):
    def decorate(method):
        method.requirement_ids = list(requirements)
        return method
    return decorate


class BankAccountRequirementTests(unittest.TestCase):
    @covers("R01")
    def test_initial_balances(self):
        self.assertEqual(BankAccount().balance, 0)
        for balance in (0, 1, 100):
            self.assertEqual(BankAccount(balance).balance, balance)

    @covers("R02")
    def test_deposit_updates_and_returns_balance(self):
        for balance, amount in ((0, 1), (100, 20), (5, 9)):
            account = BankAccount(balance)
            self.assertEqual(account.deposit(amount), balance + amount)
            self.assertEqual(account.balance, balance + amount)

    @covers("R02")
    def test_zero_deposit(self):
        account = BankAccount(100)
        self.assertEqual(account.deposit(0), 100)
        self.assertEqual(account.balance, 100)

    @covers("R03")
    def test_negative_deposit_error(self):
        account = BankAccount(100)
        with self.assertRaises(ValueError) as error:
            account.deposit(-20)
        self.assertEqual(str(error.exception), "Invalid amount")

    @covers("R03")
    def test_negative_deposit_preserves_balance(self):
        account = BankAccount(100)
        with self.assertRaises(ValueError):
            account.deposit(-20)
        self.assertEqual(account.balance, 100)

    @covers("R04")
    def test_withdraw_updates_and_returns_balance(self):
        account = BankAccount(100)
        self.assertEqual(account.withdraw(20), 80)
        self.assertEqual(account.balance, 80)

    @covers("R04")
    def test_withdraw_entire_balance(self):
        account = BankAccount(100)
        self.assertEqual(account.withdraw(100), 0)
        self.assertEqual(account.balance, 0)

    @covers("R04")
    def test_zero_withdrawal(self):
        account = BankAccount(100)
        self.assertEqual(account.withdraw(0), 100)
        self.assertEqual(account.balance, 100)

    @covers("R05")
    def test_negative_withdrawal_error(self):
        account = BankAccount(100)
        with self.assertRaises(ValueError) as error:
            account.withdraw(-20)
        self.assertEqual(str(error.exception), "Invalid amount")

    @covers("R05")
    def test_negative_withdrawal_preserves_balance(self):
        account = BankAccount(100)
        with self.assertRaises(ValueError):
            account.withdraw(-20)
        self.assertEqual(account.balance, 100)

    @covers("R06")
    def test_insufficient_withdrawal_error(self):
        account = BankAccount(100)
        with self.assertRaises(ValueError) as error:
            account.withdraw(101)
        self.assertEqual(str(error.exception), "Insufficient balance.")

    @covers("R06")
    def test_insufficient_withdrawal_preserves_balance(self):
        account = BankAccount(100)
        with self.assertRaises(ValueError):
            account.withdraw(101)
        self.assertEqual(account.balance, 100)

    @covers("R07")
    def test_view_returns_balance(self):
        self.assertEqual(BankAccount(100).view_balance(), 100)

    @covers("R07")
    def test_repeated_views_preserve_balance(self):
        account = BankAccount(100)
        self.assertEqual(account.view_balance(), 100)
        self.assertEqual(account.view_balance(), 100)
        self.assertEqual(account.balance, 100)

    @covers("R08")
    def test_transfer_updates_both_accounts(self):
        source, target = BankAccount(100), BankAccount(30)
        source.transfer(target, 20)
        self.assertEqual((source.balance, target.balance), (80, 50))

    @covers("R08")
    def test_transfer_entire_balance(self):
        source, target = BankAccount(100), BankAccount(30)
        source.transfer(target, 100)
        self.assertEqual((source.balance, target.balance), (0, 130))

    @covers("R08")
    def test_transfer_conserves_combined_balance(self):
        for initial in (0, 1, 10, 100):
            for target_initial in (0, 30):
                for amount in {0, initial // 2, initial}:
                    source, target = BankAccount(initial), BankAccount(target_initial)
                    source.transfer(target, amount)
                    self.assertEqual(source.balance, initial - amount)
                    self.assertEqual(target.balance, target_initial + amount)
                    self.assertEqual(source.balance + target.balance, initial + target_initial)

    @covers("R09")
    def test_negative_transfer_error(self):
        source, target = BankAccount(100), BankAccount(30)
        with self.assertRaises(ValueError) as error:
            source.transfer(target, -20)
        self.assertEqual(str(error.exception), "Invalid amount")

    @covers("R09")
    def test_negative_transfer_preserves_both_balances(self):
        source, target = BankAccount(100), BankAccount(30)
        with self.assertRaises(ValueError):
            source.transfer(target, -20)
        self.assertEqual((source.balance, target.balance), (100, 30))

    @covers("R10")
    def test_insufficient_transfer_error(self):
        source, target = BankAccount(100), BankAccount(30)
        with self.assertRaises(ValueError) as error:
            source.transfer(target, 101)
        self.assertEqual(str(error.exception), "Insufficient balance.")

    @covers("R10")
    def test_insufficient_transfer_preserves_both_balances(self):
        source, target = BankAccount(100), BankAccount(30)
        with self.assertRaises(ValueError):
            source.transfer(target, 101)
        self.assertEqual((source.balance, target.balance), (100, 30))

    @covers("R11")
    def test_zero_transfer_preserves_both_balances(self):
        source, target = BankAccount(100), BankAccount(30)
        source.transfer(target, 0)
        self.assertEqual((source.balance, target.balance), (100, 30))

    @covers("R12")
    def test_operation_sequence_preserves_expected_state(self):
        source, target = BankAccount(100), BankAccount(30)
        source.deposit(20)
        source.withdraw(10)
        source.transfer(target, 40)
        target.withdraw(5)
        self.assertEqual((source.balance, target.balance), (70, 65))

    @covers("R12", "R03", "R06", "R09")
    def test_rejections_do_not_corrupt_later_operations(self):
        source, target = BankAccount(100), BankAccount(30)
        for operation in (lambda: source.deposit(-1), lambda: source.withdraw(101),
                          lambda: source.transfer(target, -1)):
            with self.assertRaises(ValueError):
                operation()
        source.transfer(target, 20)
        self.assertEqual((source.balance, target.balance), (80, 50))

    @covers("R13")
    def test_public_api_is_preserved(self):
        signatures = {"__init__": ("self", "balance"), "deposit": ("self", "amount"),
                      "withdraw": ("self", "amount"), "view_balance": ("self",),
                      "transfer": ("self", "other_account", "amount")}
        for name, names in signatures.items():
            signature = inspect.signature(getattr(BankAccount, name))
            self.assertEqual(tuple(signature.parameters), names)
        self.assertEqual(inspect.signature(BankAccount.__init__).parameters["balance"].default, 0)
        self.assertTrue(hasattr(BankAccount(), "balance"))
