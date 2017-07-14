<?php

$recepient = "abakan1212@gmail.com";
$sitename = "sitename";

$name = trim($_POST["name"]);
$phone = trim($_POST["phone"]);
$Message = "Имя: $name \nТелефон: $phone \nТекст: $text";

$pagetitle = "Новая заявка с сайта \"$sitename\"";
mail($recepient, $pagetitle, $Message, "Content-type: text/plain; charset=\"utf-8\"\n From: $recepient");
