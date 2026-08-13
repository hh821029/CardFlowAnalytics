using CsvHelper.Configuration;
using RewardEngine.Core.Models;

namespace RewardEngine.Core.Loaders;

/// <summary>
/// 對應 dim_billing_history_private.csv 欄位對齊與日期格式轉型
/// 欄標: bank_name, card_type, statement_month, closing_date, actual_closing_date
/// </summary>
public class BillingHistoryRecordMap : ClassMap<BillingHistoryRecord>
{
    public BillingHistoryRecordMap()
    {
        Map(m => m.BankName).Name("bank_name");
        Map(m => m.CardType).Name("card_type");
        Map(m => m.StatementMonth).Name("statement_month");

        Map(m => m.ClosingDate).Name("closing_date").TypeConverterOption.Format("yyyy-MM-dd");
        Map(m => m.ActualClosingDate).Name("actual_closing_date").TypeConverterOption.Format("yyyy-MM-dd");
    }
}
