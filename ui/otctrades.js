var settings = require("./settings.js")();
require("./elements.js")();
require("./utils.js")();

var OTC_TRADES_TABLE = null;

function update_valhtml(selector_text, val) {
    $(selector_text).val(val);
    $(selector_text).html(val);
}

function format (d) {
    // `d` is the original data object for the row
    return '<table cellpadding="5" cellspacing="0" border="0" style="padding-left:50px;">'+
        '<tr>'+
        '<td>Extra Info</td>'+
        '<td>'+d.notes+'</td>'+
        '</tr>'+
        '<tr>'+
        '<td>Links:</td>'+
        '<td>'+d.link+'</td>'+
        '</tr>'+
        '<tr>'+
        '<td>Fee:</td>'+
        '<td>'+d.fee+' '+d.fee_currency+'</td>'+
        '</tr>'+
        '</table>';
}

function edit_otc_trade(row) {
    let data = row.data();
    $('#otc_time').val(timestamp_to_date(data.timestamp));
    $('#otc_pair').val(data.pair);
    $('#otc_type').val(data.type);
    $('#otc_amount').val(data.amount);
    $('#otc_rate').val(data.rate);
    $('#otc_fee').val(data.fee);
    $('#otc_link').val(data.link);
    $('#otc_notes').val(data.notes);

    update_valhtml('#otctradesubmit', 'Edit Trade');
}

function delete_otc_trade(row) {
    let data = row.data();
    // TODO: When using sql just use primary key here
    // and now send the data to the python process
    client.invoke(
        'delete_otctrade',
        data,
        (error, res) => {
            if (error || res == null) {
                showError('Error at Trade Deletion', error);
            } else {
                if (!res['result']) {
                    showError('Error at Trade Deletion', res['message']);
                } else {
                    showInfo('Succcess', 'Trade Deleted');
                    reload_table_data();
                }
            }
        });
}

function reload_table_data() {
    client.invoke("query_otctrades", (error, result) => {
        if (error || result == null) {
            console.log("Error at querying OTC trades: " + error);
        } else {
            update_valhtml('#otc_time', '');
            update_valhtml('#otc_pair', '');
            update_valhtml('#otc_amount', '');
            update_valhtml('#otc_rate', '');
            update_valhtml('#otc_fee', '');
            update_valhtml('#otc_link', '');
            update_valhtml('#otc_notes', '');

            OTC_TRADES_TABLE.update(result);
        }
    });
}

function create_otctrades_table() {
    var str = '<div class="row"><div class="col-lg-12"><h1 class=page-header">OTC Trades List</h1></div></div>';
    str += '<div class="row"><table id="table_otctrades"><thead><tr><th></th><th>Pair</th><th>Type</th><th>Amount</th><th>Rate</th><th>Time</th></tr/></thead><tbody id="table_otctrades_body"></tbody></table></div>';
    $(str).appendTo($('#page-wrapper'));
    client.invoke("query_otctrades", (error, result) => {
        if (error || result == null) {
            console.log("Error at querying OTC trades: " + error);
        } else {
            for (let i = 0; i < result.length; i++) {
                let str = '<tr><td></td><td></td/><td></td><td></td></tr>';
                $(str).appendTo($('#table_otctrades_body'));
            }
            OTC_TRADES_TABLE = $('#table_otctrades').DataTable({
                "data": result,
                "columns": [
                    {
                        "className": 'details-control',
                        "orderable": false,
                        "data": null,
                        "defaultContent": '',
                        "render": function () {
                            return '<i class="fa fa-plus-square" aria-hidden="true"></i>';
                        },
                        width:"15px"
                    },
                    { "data": "pair" },
                    { "data": "type" },
                    { "data": "amount" },
                    { "data": "rate" },
                    {
                        "render": function (data, type, row) {
                            if (type == 'sort') {
                                return data;
                            }
                            return timestamp_to_date(data);
                        },
                        "data": "timestamp"
                    },
                ],
                "order": [[5, 'asc']],
                drawCallback : dt_edit_drawcallback('table_otctrades', edit_otc_trade, delete_otc_trade)
            });
            // Add event listener for opening and closing details
            $('#table_otctrades tbody').on('click', 'td.details-control', function () {
                var tr = $(this).closest('tr');
                var tdi = tr.find("i.fa");
                var row = OTC_TRADES_TABLE.row(tr);

                if (row.child.isShown()) {
                    // This row is already open - close it
                    row.child.hide();
                    tr.removeClass('shown');
                    tdi.first().removeClass('fa-minus-square');
                    tdi.first().addClass('fa-plus-square');
                }
                else {
                    // Open this row
                    row.child(format(row.data())).show();
                    tr.addClass('shown');
                    tdi.first().removeClass('fa-plus-square');
                    tdi.first().addClass('fa-minus-square');
                }
            } );
        }
    });
}

function create_otctrades_ui() {
    var str = '<div class="row"><div class="col-lg-12"><h1 class="page-header">OTC Trades Management</h1></div></div>';
    str += '<div class="row"><div class="col-lg-12"><div class="panel panel-default"><div class="panel-heading">Register New Trade</div><div class="panel-body"></div></div></div></div>';
    $('#page-wrapper').html(str);

    str = form_entry('time', 'otc_time', '', 'Time that the trade took place');
    str += form_entry('pair', 'otc_pair', '', 'Asset pair for the trade');
    str += form_select('trade type', 'otc_type', ['buy', 'sell'], '');
    str += form_entry('amount', 'otc_amount', '', 'Amount bought/sold');
    str += form_entry('rate', 'otc_rate', '', 'Rate of the trade');
    str += form_entry('fee', 'otc_fee', '', 'Fee if any that the trade occured');
    str += form_entry('link', 'otc_link', '', 'A link to the trade. e.g.: in an explorer');
    str += form_text('Enter additional notes', 'otc_notes', 3, '', 'Additional notes to store for the trade');
    str += form_button('Add Trade', 'otctradesubmit');
    $(str).appendTo($('.panel-body'));

    create_otctrades_table();
}

function add_otctrades_listeners() {
    $('#otctradesubmit').click(function(event) {
        event.preventDefault();
        let otc_time = $('#otc_time').val();
        let otc_pair = $('#otc_pair').val();
        let otc_type = $('#otc_type').val();
        let otc_amount = $('#otc_amount').val();
        let otc_rate = $('#otc_rate').val();
        let otc_fee = $('#otc_fee').val();
        let otc_link = $('#otc_link').val();
        let otc_notes = $('#otc_notes').val();
        let payload = {
            'otc_time': otc_time,
            'otc_pair': otc_pair,
            'otc_type': otc_type,
            'otc_amount': otc_amount,
            'otc_rate': otc_rate,
            'otc_fee': otc_fee,
            'otc_link': otc_link,
            'otc_notes': otc_notes
        };

        // depending on the type of button value we call different function
        let command = 'add_otctrade';
        if ($('#otctradesubmit').val() == 'Edit Trade') {
            command = 'edit_otctrade';
        }

        // and now send the data to the python process
        client.invoke(
            command,
            payload,
            (error, res) => {
                if (error || res == null) {
                    showError('Trade Addition Error', error);
                } else {
                    if (!res['result']) {
                        showError('Trade Addition Error', res['message']);
                    } else {
                        showInfo('Success', 'Trade submitted');
                        reload_table_data();
                        // also make sure we are back to adding a trade
                        // in case we were editing
                        $('#otctradesubmit').val('Add Trade');
                        $('#otctradesubmit').html('Add Trade');
                    }
                }
            });

    });
    $('#otc_time').datetimepicker({
        format: settings.datetime_format
    });
}

module.exports = function() {
    this.create_otctrades_ui = create_otctrades_ui;
    this.add_otctrades_listeners = add_otctrades_listeners;
};
