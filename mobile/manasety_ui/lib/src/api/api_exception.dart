/// تسلسل الاستثناءات المتولّدة عن طبقة الشبكة.
sealed class ApiException implements Exception {
  final String message;
  const ApiException(this.message);
  @override
  String toString() => 'ApiException($message)';
}

class UnauthorizedException extends ApiException {
  const UnauthorizedException([super.message = 'انتهت الجلسة، يرجى إعادة الدخول']);
}

class ForbiddenException extends ApiException {
  const ForbiddenException([super.message = 'لا تملك صلاحية تنفيذ هذا الإجراء']);
}

class NotFoundException extends ApiException {
  const NotFoundException([super.message = 'لم يتم العثور على المورد المطلوب']);
}

class ValidationException extends ApiException {
  final Map<String, String>? fields;
  const ValidationException(super.message, {this.fields});
}

class NetworkException extends ApiException {
  const NetworkException([super.message = 'تعذّر الاتصال بالخادم، تحقّق من الإنترنت']);
}

class ServerException extends ApiException {
  const ServerException([super.message = 'حدث خلل في الخادم، حاول لاحقًا']);
}
