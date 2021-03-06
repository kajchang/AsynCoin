var interval;

function connect(URL) {
    $.ajax({
        url: "http://" + URL + "/config",
        success: config => {
            clearInterval(interval);

            $("#icon").attr("src", "images/success.png");

            $("#blockreward").empty();
            $("#difficulty").empty();

            $.get("http://" + URL + "/height", function(height) {
                var height = parseInt(height);

                $("#difficulty").append('<li class="list-group-item">' + config["DIFFICULTY_ADJUST"] + ' Blocks Between Difficulty Adjustments</li>');
                $("#difficulty").append('<li class="list-group-item">' + (config["DIFFICULTY_ADJUST"] - height % config["DIFFICULTY_ADJUST"]) + ' Blocks Until Next Difficulty Adjustment</li>');

                $("#blockreward").append('<li class="list-group-item">' + config["INITIAL_REWARD"] / 2 ** Math.floor(height / config["REWARD_HALVING"]) + " Coins per Block</li>");
                $("#blockreward").append('<li class="list-group-item">Reward Halving Every ' + config["REWARD_HALVING"] + " Blocks</li>");
                $("#blockreward").append('<li class="list-group-item">' + (config["REWARD_HALVING"] - height % config["REWARD_HALVING"]) + " Blocks Until Next Reward Halving</li>");
            });

            $.get("http://" + URL + "/difficulty", function(difficulty) {
                $("#difficulty").prepend('<li class="list-group-item">' + 16 ** difficulty + ' Hashes per Block</li>');
            });
        },
        error: () => {
            clearInterval(interval);

            $('#icon').attr("src", "images/failure.png");

            interval = setInterval(function() {
                connect($('#node-uri').val())
            }, 10000);

            $("#blockreward").empty();
            $("#difficulty").empty();

            $("#blockreward").append('<li class="list-group-item">Unable to Connect.</li>');
            $("#difficulty").append('<li class="list-group-item">Unable to Connect.</li>');
        }
    });
}


$(document).ready(() => {
    // https://stackoverflow.com/questions/20194722/can-you-get-a-users-local-lan-ip-address-via-javascript
    window.RTCPeerConnection = window.RTCPeerConnection || window.mozRTCPeerConnection || window.webkitRTCPeerConnection; //compatibility for Firefox and chrome
    var pc = new RTCPeerConnection({
        iceServers: []
    });
    pc.createDataChannel(''); //create a bogus data channel
    pc.createOffer(pc.setLocalDescription.bind(pc), () => {}); // create offer and set local description
    pc.onicecandidate = ice => {
        if (ice && ice.candidate && ice.candidate.candidate) {
            var myIP = /([0-9]{1,3}(\.[0-9]{1,3}){3}|[a-f0-9]{1,4}(:[a-f0-9]{1,4}){7})/.exec(ice.candidate.candidate)[1];
            pc.onicecandidate = () => {};
            connect(myIP + ":8000");


            $("#node-uri").attr("value", myIP + ":8000");
            $("#node-uri").on("input", () => {
                connect(this.value);
            });
        }
    }
});