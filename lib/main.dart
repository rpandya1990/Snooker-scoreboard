import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'pages/main_menu_page.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setPreferredOrientations([
    DeviceOrientation.landscapeRight,
    DeviceOrientation.landscapeLeft,
  ]);
  runApp(SnookerScoreboardApp());
}

class SnookerScoreboardApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Snooker Scoreboard',
      theme: ThemeData(
        brightness: Brightness.light,
        scaffoldBackgroundColor: Colors.grey[200],
        textTheme: TextTheme(
          bodyMedium: TextStyle(color: Colors.black87, fontSize: 18),
        ),
        colorScheme: ColorScheme.light(
          primary: Colors.teal,
          secondary: Colors.red,
        ),
      ),
      home: MainMenuPage(),
    );
  }
}
