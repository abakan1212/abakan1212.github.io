
<?php
$name = htmlspecialchars($_POST['name']);
$email = htmlspecialchars($_POST['email']);
if ($name =''|| $email =''||) {
  echo 'Заполните все поля';
  exit;
}
//Отправка
$subject = "?utf-8?B?".base64_encode($subject)."?=";
$header = "From: $email\r\nReply-to: $email\r\nContent-type: text/html; charset=utf-8\r\n";
if(mail("abakan1212@gmail.com", $subject, $message, $headers))
echo "Сообщение отправлено";
else
  echo "Сообщение не отправлено";
 ?>
