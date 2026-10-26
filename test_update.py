import unittest
import update

class LogicTests(unittest.TestCase):
    def test_hypothetical_entry_is_strictly_after_filing(self):
        prices=[['2026-10-20',100],['2026-10-21',105],['2026-10-22',110]]
        val, date=update.after_price(prices,'2026-10-20')
        self.assertEqual((val,date),(105,'2026-10-21'))
    def test_a_purchase_gets_after_disclosure_returns(self):
        trades=[{'ticker':'ABCD','type':'buy','filedDate':'2026-10-20'}]
        update.enrich(trades,{'ABCD':[['2026-10-20',100],['2026-10-21',105],['2026-10-22',110]]})
        self.assertEqual(trades[0]['returnPct'],4.76)
    def test_sale_never_acts_like_purchased_holding(self):
        trades=[{'ticker':'ABCD','type':'sell','filedDate':'2026-10-20'}]
        update.enrich(trades,{'ABCD':[['2026-10-20',100],['2026-10-21',105],['2026-10-22',110]]})
        self.assertIsNone(trades[0]['returnPct'])
    def test_no_future_price_means_unavailable_return(self):
        trades=[{'ticker':'ABCD','type':'buy','filedDate':'2026-10-22'}]
        update.enrich(trades,{'ABCD':[['2026-10-20',100],['2026-10-21',105],['2026-10-22',110]]})
        self.assertIsNone(trades[0]['returnPct'])
    def test_unsupported_ticker_removed(self):
        self.assertEqual(update.clean_symbol('SPY.A'), 'SPY-A')
        self.assertEqual(update.clean_symbol('$NOT_REAL!'), '')

if __name__=='__main__':unittest.main()
